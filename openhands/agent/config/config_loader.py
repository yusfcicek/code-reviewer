"""
Config Loader - Enterprise Review Policy Yönetimi.

YAML dosyasından veya environment variable'lardan policy yükler.
"""

import os
import yaml
from dataclasses import dataclass, field
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
    2. YAML dosyası (review_policy.yaml)
    3. Default değerler
    """
    
    DEFAULT_POLICY_PATHS = [
        "review_policy.yaml",
        ".review_policy.yaml",
        ".agent/review_policy.yaml",
        "config/review_policy.yaml",
    ]
    
    ENV_PREFIX = "REVIEW_POLICY_"
    
    def __init__(self):
        self._cached_policy: Optional[ReviewPolicy] = None
    
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
    
    def _load_from_file(self, policy_path: str = None) -> Optional[Dict]:
        """YAML dosyasından policy yükler."""
        # Verilen path veya default path'leri dene
        paths_to_try = [policy_path] if policy_path else self.DEFAULT_POLICY_PATHS
        
        for path in paths_to_try:
            if path and os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                        print(f"[CONFIG] Loaded policy from: {path}")
                        return data
                except Exception as e:
                    print(f"[CONFIG] Error loading {path}: {e}")
        
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
        
        # Triage overrides
        if 'triage' in overrides:
            for key, value in overrides['triage'].items():
                if hasattr(base.triage, key):
                    setattr(base.triage, key, value)
        
        # Security overrides
        if 'security' in overrides:
            for key, value in overrides['security'].items():
                if hasattr(base.security, key):
                    setattr(base.security, key, value)
        
        # Quality overrides
        if 'quality' in overrides:
            for key, value in overrides['quality'].items():
                if hasattr(base.quality, key):
                    setattr(base.quality, key, value)
        
        # Performance overrides
        if 'performance' in overrides:
            for key, value in overrides['performance'].items():
                if hasattr(base.performance, key):
                    setattr(base.performance, key, value)
        
        # Gate overrides
        if 'gate' in overrides:
            for key, value in overrides['gate'].items():
                if hasattr(base.gate, key):
                    setattr(base.gate, key, value)
        
        # Custom rules
        if 'custom_rules' in overrides:
            base.custom_rules.update(overrides['custom_rules'])
        
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
