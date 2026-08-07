"""Loads a :class:`~code_reviewer.domain.policy.ReviewPolicy` from disk or environment.

Resolution order, highest priority first: the path given on the command line,
known file names in the working directory, the policy shipped inside the
package, then the dataclass defaults. Environment variables override whatever
the file provided.

The packaged file used to be unreachable because every candidate path was
relative to the working directory (finding F-04).
"""

import os
from importlib import resources
from pathlib import Path

import yaml

from code_reviewer.domain.policy import (
    ReviewPolicy,
)
from code_reviewer.infrastructure.observability.logging import get_logger

logger = get_logger(__name__)


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
    PACKAGED_POLICY_ANCHOR = "code_reviewer.infrastructure.config"
    PACKAGED_POLICY_NAME = "review_policy.yaml"

    ENV_PREFIX = "REVIEW_POLICY_"

    def __init__(self):
        self._cached_policy: ReviewPolicy | None = None
        #: Where the loaded policy came from, for diagnostics.
        self.source: str | None = None

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

    def packaged_policy_path(self) -> Path | None:
        """Absolute path of the policy file shipped inside the package."""
        try:
            candidate = resources.files(self.PACKAGED_POLICY_ANCHOR) / self.PACKAGED_POLICY_NAME
            path = Path(str(candidate))
            return path if path.is_file() else None
        except (ModuleNotFoundError, FileNotFoundError, TypeError):
            return None

    def _candidate_paths(self, policy_path: str = None) -> list[str]:
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

    def _load_from_file(self, policy_path: str = None) -> dict | None:
        """YAML dosyasından policy yükler."""
        if policy_path and not os.path.exists(policy_path):
            logger.warning(
                "Policy file not found; falling back", extra={"fields": {"path": policy_path}}
            )

        for path in self._candidate_paths(policy_path):
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                logger.warning(
                    "Could not read policy file", extra={"fields": {"path": path, "error": str(e)}}
                )
                continue

            if not isinstance(data, dict):
                logger.warning(
                    "Ignoring policy file: expected a YAML mapping",
                    extra={"fields": {"path": path}},
                )
                continue

            self.source = path
            logger.info("Policy loaded", extra={"fields": {"source": path}})
            return data

        logger.info("No policy file found; using built-in defaults")
        return None

    def _load_from_env(self) -> dict:
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
            "REVIEW_POLICY_FAIL_ON_CRITICAL": (
                "gate",
                "fail_pipeline_on_critical",
                self._parse_bool,
            ),
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
                    logger.warning(
                        "Ignoring invalid environment override",
                        extra={"fields": {"variable": env_var, "value": value}},
                    )

        return overrides

    def _parse_bool(self, value: str) -> bool:
        """String'i bool'a çevirir."""
        return value.lower() in ("true", "1", "yes", "on")

    def _merge_policies(self, base: ReviewPolicy, overrides: dict) -> ReviewPolicy:
        """Override'ları base policy'ye uygular."""
        if not overrides:
            return base

        # Version: a policy file that declares its own version was previously
        # merged without it, so every report claimed the default "1.0".
        if "version" in overrides:
            base.version = str(overrides["version"])

        # A YAML section that is present but empty parses as None, not as an
        # empty mapping. The shipped policy ends with a `custom_rules:` heading
        # followed only by comments, which used to make merging raise
        # TypeError the moment the file was actually loaded.
        for section in ("triage", "security", "quality", "performance", "gate"):
            values = overrides.get(section)
            if not isinstance(values, dict):
                if values is not None:
                    logger.warning(
                        "Ignoring policy section: expected a mapping",
                        extra={"fields": {"section": section, "got": type(values).__name__}},
                    )
                continue

            target = getattr(base, section)
            for key, value in values.items():
                if hasattr(target, key):
                    setattr(target, key, value)
                else:
                    logger.warning(
                        "Ignoring unknown policy key", extra={"fields": {"key": f"{section}.{key}"}}
                    )

        custom_rules = overrides.get("custom_rules")
        if isinstance(custom_rules, dict):
            base.custom_rules.update(custom_rules)

        return base

    def get_cached(self) -> ReviewPolicy | None:
        """Cache'lenmiş policy'yi döner."""
        return self._cached_policy

    def to_yaml(self, policy: ReviewPolicy) -> str:
        """Policy'yi YAML string'e çevirir."""
        data = {
            "version": policy.version,
            "triage": {
                "skip_patterns": policy.triage.skip_patterns,
                "max_lines_for_auto": policy.triage.max_lines_for_auto,
                "max_lines_for_quick": policy.triage.max_lines_for_quick,
                "allow_only_comments": policy.triage.allow_only_comments,
                "allow_only_formatting": policy.triage.allow_only_formatting,
                "allow_test_files": policy.triage.allow_test_files,
            },
            "security": {
                "block_on_critical": policy.security.block_on_critical,
                "block_on_high": policy.security.block_on_high,
                "block_on_medium": policy.security.block_on_medium,
                "banned_patterns": policy.security.banned_patterns,
            },
            "quality": {
                "max_class_methods": policy.quality.max_class_methods,
                "max_function_lines": policy.quality.max_function_lines,
                "max_cyclomatic_complexity": policy.quality.max_cyclomatic_complexity,
            },
            "performance": {
                "alert_on_n_squared": policy.performance.alert_on_n_squared,
                "alert_on_n_plus_one": policy.performance.alert_on_n_plus_one,
            },
            "gate": {
                "quality_score_threshold": policy.gate.quality_score_threshold,
                "security_score_threshold": policy.gate.security_score_threshold,
                "fail_pipeline_on_critical": policy.gate.fail_pipeline_on_critical,
            },
        }
        return yaml.dump(data, default_flow_style=False, allow_unicode=True)


def load_policy(policy_path: str = None) -> ReviewPolicy:
    """Convenience function - policy yükler."""
    return ReviewPolicyLoader().load(policy_path)


def get_default_policy() -> ReviewPolicy:
    """Default policy döner."""
    return ReviewPolicy()
