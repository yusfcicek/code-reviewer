"""
Config Loader - Enterprise Review Policy Yönetimi.

YAML dosyasından veya environment variable'lardan policy yükler.
"""

import os
import yaml
from dataclasses import dataclass, field
from importlib import resources
from typing import List, Dict, Optional, Any
from pathlib import Path


@dataclass
class TriagePolicy:
    """Triage politikası."""
    skip_patterns: List[str] = field(default_factory=lambda: [
        r".*\.md$", r".*\.txt$", r".*\.rst$", r"README.*", r"CHANGELOG.*", r"LICENSE.*",
        r"\.gitignore", r"\.gitattributes", r".*\.json$", r".*\.yaml$", r".*\.yml$",
        r"requirements.*\.txt$", r"package.*\.json$", r"Dockerfile", r"Makefile"
    ])
    max_lines_for_auto: int = 10
    max_lines_for_quick: int = 50
    allow_only_comments: bool = True
    allow_only_formatting: bool = True
    allow_test_files: bool = True


@dataclass
class SecurityPolicy:
    """Güvenlik politikası."""
    block_on_critical: bool = True
    block_on_high: bool = True
    block_on_medium: bool = False
    
    banned_patterns: List[str] = field(default_factory=lambda: [
        r"eval\s*\(", r"exec\s*\(", r"pickle\.loads", r"shell=True"
    ])
    
    secret_patterns: List[str] = field(default_factory=lambda: [
        r"password\s*=\s*['\"][^'\"]+['\"]",
        r"api[_-]?key\s*=",
        r"-----BEGIN.*PRIVATE KEY-----"
    ])


@dataclass
class QualityPolicy:
    """Kod kalite politikası."""
    max_class_methods: int = 15
    max_function_lines: int = 100
    max_cyclomatic_complexity: int = 15
    min_duplicate_lines: int = 8
    
    # SOLID enforcement
    enforce_srp: bool = True
    enforce_dip: bool = True
    
    # Error handling
    block_empty_catches: bool = True
    block_generic_exceptions: bool = False


@dataclass
class PerformancePolicy:
    """Performans politikası."""
    alert_on_n_squared: bool = True
    alert_on_n_plus_one: bool = True
    alert_on_memory_leak: bool = True
    max_nested_loops: int = 3


@dataclass
class GatePolicy:
    """Review gate politikası."""
    quality_score_threshold: int = 60
    security_score_threshold: int = 70
    performance_score_threshold: int = 50
    
    fail_pipeline_on_critical: bool = True
    fail_pipeline_on_quality_below: int = 50
    
    # Notification
    notify_on_critical: bool = True
    notify_channels: List[str] = field(default_factory=list)


@dataclass
class ReviewPolicy:
    """Tüm review politikalarını kapsayan ana yapı."""
    version: str = "1.0"
    
    triage: TriagePolicy = field(default_factory=TriagePolicy)
    security: SecurityPolicy = field(default_factory=SecurityPolicy)
    quality: QualityPolicy = field(default_factory=QualityPolicy)
    performance: PerformancePolicy = field(default_factory=PerformancePolicy)
    gate: GatePolicy = field(default_factory=GatePolicy)
    
    # Custom overrides
    custom_rules: Dict[str, Any] = field(default_factory=dict)


class ReviewPolicyLoader:
    """
    Enterprise review policy'lerini yükler.

    Yükleme sırası (öncelik):
    1. Environment variables (REVIEW_POLICY_*)
    2. ``--policy`` ile verilen dosya
    3. Çalışma dizinindeki bilinen dosya adları
    4. Pakete gömülü ``review_policy.yaml``
    5. Dataclass default değerleri

    Paket içindeki dosya eskiden hiç denenmiyordu: tüm adaylar çalışma
    dizinine göreliydi, dolayısıyla ``--policy`` verilmediğinde ajan sessizce
    dar dataclass varsayılanlarıyla çalışıyordu (bkz. F-04).
    """

    #: Working-directory candidates, in order.
    DEFAULT_POLICY_PATHS = [
        "review_policy.yaml",
        ".review_policy.yaml",
        ".agent/review_policy.yaml",
        "config/review_policy.yaml",
    ]

    #: Package and file name of the policy shipped with the distribution.
    PACKAGED_POLICY_ANCHOR = "openhands.agent.config"
    PACKAGED_POLICY_NAME = "review_policy.yaml"

    ENV_PREFIX = "REVIEW_POLICY_"

    def __init__(self):
        self._cached_policy: Optional[ReviewPolicy] = None
        #: Where the loaded policy came from, for diagnostics.
        self.source: Optional[str] = None

    def load(self, policy_path: str = None) -> ReviewPolicy:
        """
        Policy'yi yükler. Önce dosya, sonra env var'lar kontrol edilir.

        Args:
            policy_path: Opsiyonel YAML dosya yolu

        Returns:
            ReviewPolicy: Yüklenen policy
        """
        # 1. Start with defaults
        policy = ReviewPolicy()

        # 2. Try to load from file
        file_policy = self._load_from_file(policy_path)
        if file_policy:
            policy = self._merge_policies(policy, file_policy)

        # 3. Override with environment variables
        env_overrides = self._load_from_env()
        if env_overrides:
            policy = self._merge_policies(policy, env_overrides)

        self._cached_policy = policy
        return policy

    def packaged_policy_path(self) -> Optional[Path]:
        """Absolute path of the policy file shipped inside the package."""
        try:
            candidate = resources.files(self.PACKAGED_POLICY_ANCHOR) / self.PACKAGED_POLICY_NAME
            path = Path(str(candidate))
            return path if path.is_file() else None
        except (ModuleNotFoundError, FileNotFoundError, TypeError):
            return None

    def _candidate_paths(self, policy_path: str = None) -> List[str]:
        """Ordered candidates: explicit, working directory, then packaged.

        An explicit path that does not exist falls through rather than
        aborting, so a stale ``--policy`` in a pipeline definition degrades to
        the shipped rules instead of to no rules at all. The chosen source is
        recorded in :attr:`source` and printed, because "which policy actually
        applied" is the first question when a review surprises someone.
        """
        candidates = []
        if policy_path:
            candidates.append(policy_path)
        candidates.extend(self.DEFAULT_POLICY_PATHS)

        packaged = self.packaged_policy_path()
        if packaged is not None:
            candidates.append(str(packaged))

        return candidates

    def _load_from_file(self, policy_path: str = None) -> Optional[Dict]:
        """YAML dosyasından policy yükler."""
        if policy_path and not os.path.exists(policy_path):
            print(f"[CONFIG] Policy file not found: {policy_path}; falling back.")

        for path in self._candidate_paths(policy_path):
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                print(f"[CONFIG] Error loading {path}: {e}")
                continue

            if not isinstance(data, dict):
                print(f"[CONFIG] Ignoring {path}: expected a YAML mapping.")
                continue

            self.source = path
            print(f"[CONFIG] Loaded policy from: {path}")
            return data

        print("[CONFIG] No policy file found; using built-in defaults.")
        return None
    
    def _load_from_env(self) -> Dict:
        """Environment variable'lardan override'ları yükler."""
        overrides = {}
        
        # Bilinen env var'ları kontrol et
        env_mappings = {
            "REVIEW_POLICY_MAX_LINES_AUTO": ("triage", "max_lines_for_auto", int),
            "REVIEW_POLICY_MAX_LINES_QUICK": ("triage", "max_lines_for_quick", int),
            "REVIEW_POLICY_BLOCK_CRITICAL": ("security", "block_on_critical", self._parse_bool),
            "REVIEW_POLICY_BLOCK_HIGH": ("security", "block_on_high", self._parse_bool),
            "REVIEW_POLICY_QUALITY_THRESHOLD": ("gate", "quality_score_threshold", int),
            "REVIEW_POLICY_SECURITY_THRESHOLD": ("gate", "security_score_threshold", int),
            "REVIEW_POLICY_FAIL_ON_CRITICAL": ("gate", "fail_pipeline_on_critical", self._parse_bool),
            "REVIEW_POLICY_MAX_CLASS_METHODS": ("quality", "max_class_methods", int),
            "REVIEW_POLICY_MAX_FUNC_LINES": ("quality", "max_function_lines", int),
        }
        
        for env_var, (section, key, converter) in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                if section not in overrides:
                    overrides[section] = {}
                try:
                    overrides[section][key] = converter(value)
                except (ValueError, TypeError):
                    print(f"[CONFIG] Invalid value for {env_var}: {value}")
        
        return overrides
    
    def _parse_bool(self, value: str) -> bool:
        """String'i bool'a çevirir."""
        return value.lower() in ('true', '1', 'yes', 'on')
    
    def _merge_policies(self, base: ReviewPolicy, overrides: Dict) -> ReviewPolicy:
        """Override'ları base policy'ye uygular."""
        if not overrides:
            return base

        # Version: a policy file that declares its own version was previously
        # merged without it, so every report claimed the default "1.0".
        if 'version' in overrides:
            base.version = str(overrides['version'])

        # A YAML section that is present but empty parses as None, not as an
        # empty mapping. The shipped policy ends with a `custom_rules:` heading
        # followed only by comments, which used to make merging raise
        # TypeError the moment the file was actually loaded.
        for section in ('triage', 'security', 'quality', 'performance', 'gate'):
            values = overrides.get(section)
            if not isinstance(values, dict):
                if values is not None:
                    print(f"[CONFIG] Ignoring '{section}': expected a mapping, got {type(values).__name__}.")
                continue

            target = getattr(base, section)
            for key, value in values.items():
                if hasattr(target, key):
                    setattr(target, key, value)
                else:
                    print(f"[CONFIG] Ignoring unknown key '{section}.{key}'.")

        custom_rules = overrides.get('custom_rules')
        if isinstance(custom_rules, dict):
            base.custom_rules.update(custom_rules)

        return base
    
    def get_cached(self) -> Optional[ReviewPolicy]:
        """Cache'lenmiş policy'yi döner."""
        return self._cached_policy
    
    def to_yaml(self, policy: ReviewPolicy) -> str:
        """Policy'yi YAML string'e çevirir."""
        data = {
            'version': policy.version,
            'triage': {
                'skip_patterns': policy.triage.skip_patterns,
                'max_lines_for_auto': policy.triage.max_lines_for_auto,
                'max_lines_for_quick': policy.triage.max_lines_for_quick,
                'allow_only_comments': policy.triage.allow_only_comments,
                'allow_only_formatting': policy.triage.allow_only_formatting,
                'allow_test_files': policy.triage.allow_test_files,
            },
            'security': {
                'block_on_critical': policy.security.block_on_critical,
                'block_on_high': policy.security.block_on_high,
                'block_on_medium': policy.security.block_on_medium,
                'banned_patterns': policy.security.banned_patterns,
            },
            'quality': {
                'max_class_methods': policy.quality.max_class_methods,
                'max_function_lines': policy.quality.max_function_lines,
                'max_cyclomatic_complexity': policy.quality.max_cyclomatic_complexity,
            },
            'performance': {
                'alert_on_n_squared': policy.performance.alert_on_n_squared,
                'alert_on_n_plus_one': policy.performance.alert_on_n_plus_one,
            },
            'gate': {
                'quality_score_threshold': policy.gate.quality_score_threshold,
                'security_score_threshold': policy.gate.security_score_threshold,
                'fail_pipeline_on_critical': policy.gate.fail_pipeline_on_critical,
            }
        }
        return yaml.dump(data, default_flow_style=False, allow_unicode=True)


def load_policy(policy_path: str = None) -> ReviewPolicy:
    """Convenience function - policy yükler."""
    return ReviewPolicyLoader().load(policy_path)


def get_default_policy() -> ReviewPolicy:
    """Default policy döner."""
    return ReviewPolicy()
