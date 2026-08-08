"""Loads a :class:`~code_reviewer.domain.policy.ReviewPolicy` from disk or environment.

Resolution order, highest priority first: the path given on the command line,
known file names in the working directory, the policy shipped inside the
package, then the dataclass defaults. Environment variables override whatever
the file provided.

The packaged file used to be unreachable because every candidate path was
relative to the working directory (finding F-04).
"""

import dataclasses
import os
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import ClassVar

import yaml

from code_reviewer.domain.policy import (
    ReviewPolicy,
)
from code_reviewer.errors import ConfigurationError
from code_reviewer.infrastructure.observability.logging import get_logger

logger = get_logger(__name__)


def _matches(value: object, annotation: object) -> bool:
    """Whether ``value`` fits ``annotation``, loosely but usefully.

    Dataclass annotations arrive as type objects when the module does not use
    postponed evaluation, and as strings when it does. Both are normalised to
    text here, so the check does not depend on which style the policy
    dataclasses happen to be written in.

    The check is deliberately shallow: it catches a string where an int
    belongs and a list where a bool belongs, which is what a policy typo
    actually looks like. It does not verify the contents of a list.

    `bool` is tested before `int` because `True` *is* an `int` in Python, and
    a policy file should not inherit that surprise: `max_class_methods: true`
    is a mistake, not a threshold of one.
    """
    expected = getattr(annotation, "__name__", None) or str(annotation)
    expected = expected.lower()

    if "bool" in expected:
        return isinstance(value, bool)
    if "int" in expected:
        return isinstance(value, int) and not isinstance(value, bool)
    if "list" in expected:
        return isinstance(value, list)
    if "dict" in expected:
        return isinstance(value, dict)
    if "str" in expected:
        return isinstance(value, str)
    return True


class PolicyLoadError(ConfigurationError):
    """A policy file was found but could not be trusted.

    Raised rather than logged, and the distinction is the whole design. A
    policy engine that quietly falls back to defaults is worse than one that
    has none, because it is *believed*: `block_on_critcal: false` leaves the
    rule on under a name its author thinks they turned off, and nothing says
    so (finding G-10).

    The cost of failing closed is one startup error the first time someone
    typos a key — which is exactly the moment they want to hear about it.

    A ``ConfigurationError``, so the entry point exits `2`: nothing was
    reviewed, and retrying will not change that until the file is fixed.
    """


class ReviewPolicyLoader:
    """
    Loads the review policy.

    Resolution order, highest priority first:
    1. environment variables (``REVIEW_POLICY_*``)
    2. the file given to ``--policy``
    3. known file names in the working directory
    4. the ``review_policy.yaml`` bundled with the package
    5. the dataclass defaults

    The packaged file used to be unreachable: every candidate path was relative
    to the working directory, so without an explicit ``--policy`` the agent ran
    silently on the narrow dataclass defaults (finding F-04).
    """

    #: Working-directory candidates, in order.
    DEFAULT_POLICY_PATHS: ClassVar[list[str]] = [
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

    def load(self, policy_path: str | None = None) -> ReviewPolicy:
        """
        Loads the policy: the file first, then environment overrides.

        Args:
            policy_path: Optional path to a YAML policy file.

        Returns:
            ReviewPolicy: the resolved policy.
        """
        # 1. Start with defaults
        policy = ReviewPolicy()

        # 2. Try to load from file
        file_policy = self._load_from_file(policy_path)
        if file_policy:
            # The source is named in every error, because "which file said
            # this" is the first thing anyone needs when a policy is refused.
            policy = self._merge_policies(policy, file_policy, self.source or "<policy file>")

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

    def _candidate_paths(self, policy_path: str | None = None) -> list[str]:
        """Ordered candidates: explicit, working directory, then packaged.

        The chosen source is recorded in :attr:`source` and printed, because
        "which policy actually applied" is the first question when a review
        surprises someone.
        """
        candidates = []
        if policy_path:
            candidates.append(policy_path)
        candidates.extend(self.DEFAULT_POLICY_PATHS)

        packaged = self.packaged_policy_path()
        if packaged is not None:
            candidates.append(str(packaged))

        return candidates

    def _load_from_file(self, policy_path: str | None = None) -> dict | None:
        """Reads the first candidate file, refusing one it cannot trust.

        Absence is permissive, content is not (decision D-4). Finding no
        policy file is a deployment that has not configured one — a valid
        state with a documented default. Naming a file that is not there, or
        finding one that does not parse, is a claim that turned out to be
        false, and a false claim about a security policy is worth stopping
        for.

        Raises:
            PolicyLoadError: if ``policy_path`` is named and absent, or a
                candidate file is unreadable, unparseable, or not a mapping.
        """
        if policy_path and not os.path.exists(policy_path):
            raise PolicyLoadError(
                f"Policy file not found: {policy_path}. Naming a policy file is a claim "
                f"that it exists; falling back silently would run rules nobody chose."
            )

        for path in self._candidate_paths(policy_path):
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except OSError as exc:
                raise PolicyLoadError(f"Cannot read policy file {path}: {exc}") from exc
            except yaml.YAMLError as exc:
                raise PolicyLoadError(f"Invalid YAML in policy file {path}: {exc}") from exc

            if data is None:
                # An entirely empty file states nothing, which is the same as
                # having no file: silence, not a wrong claim.
                logger.info("Policy file is empty; using built-in defaults", extra={"fields": {"path": path}})
                self.source = path
                return None

            if not isinstance(data, dict):
                raise PolicyLoadError(
                    f"Policy file {path} must contain a YAML mapping at its root, got {type(data).__name__}."
                )

            self.source = path
            logger.info("Policy loaded", extra={"fields": {"source": path}})
            return data

        logger.info("No policy file found; using built-in defaults")
        return None

    def _load_from_env(self) -> dict:
        """Collects the REVIEW_POLICY_* overrides that are set."""
        overrides: dict[str, dict[str, object]] = {}

        # Only these variables are recognised; anything else is ignored.
        env_mappings: dict[str, tuple[str, str, Callable[[str], object]]] = {
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
        """Reads a boolean from an environment string."""
        return value.lower() in ("true", "1", "yes", "on")

    #: Sections a policy file may declare, besides `version` and `custom_rules`.
    POLICY_SECTIONS = ("triage", "security", "quality", "performance", "gate")

    def _merge_policies(
        self, base: ReviewPolicy, overrides: dict, source: str = "<environment>"
    ) -> ReviewPolicy:
        """Applies a mapping of overrides onto a policy in place.

        Every name is checked against the dataclass that owns it, and an
        unrecognised one stops the load. It used to be logged and skipped,
        which meant a typo produced a configuration nobody had chosen and
        nobody was told about (finding G-10).

        Raises:
            PolicyLoadError: on an unknown section or key, a section that is
                not a mapping, or a value of the wrong type.
        """
        if not overrides:
            return base

        # Version: a policy file that declares its own version was previously
        # merged without it, so every report claimed the default "1.0".
        if "version" in overrides:
            base.version = str(overrides["version"])

        self._reject_unknown_sections(overrides, source)

        # A YAML section that is present but empty parses as None, not as an
        # empty mapping. The shipped policy ends with a `custom_rules:` heading
        # followed only by comments, which used to make merging raise
        # TypeError the moment the file was actually loaded. An empty section
        # states nothing, so it is accepted and skipped.
        for section in self.POLICY_SECTIONS:
            if section not in overrides:
                continue

            values = overrides[section]
            if values is None:
                continue
            if not isinstance(values, dict):
                raise PolicyLoadError(
                    f"{source}: section '{section}' must be a mapping, got {type(values).__name__}."
                )

            target = getattr(base, section)
            for key, value in values.items():
                self._assign(target, section, key, value, source)

        custom_rules = overrides.get("custom_rules")
        if custom_rules is not None:
            if not isinstance(custom_rules, dict):
                raise PolicyLoadError(
                    f"{source}: 'custom_rules' must be a mapping, got {type(custom_rules).__name__}."
                )
            # The one section whose keys are the user's own vocabulary, so
            # there is nothing to validate them against.
            base.custom_rules.update(custom_rules)

        return base

    def _reject_unknown_sections(self, overrides: dict, source: str) -> None:
        known = {*self.POLICY_SECTIONS, "version", "custom_rules"}
        unknown = sorted(set(overrides) - known)
        if unknown:
            raise PolicyLoadError(
                f"{source}: unknown policy section(s) {', '.join(repr(s) for s in unknown)}. "
                f"Expected one of: {', '.join(sorted(known))}."
            )

    @staticmethod
    def _assign(target: object, section: str, key: str, value: object, source: str) -> None:
        """Sets one key, refusing an unknown name or a wrongly typed value."""
        declared = {f.name: f.type for f in dataclasses.fields(target)}  # type: ignore[arg-type]

        if key not in declared:
            raise PolicyLoadError(
                f"{source}: unknown key '{section}.{key}'. Expected one of: {', '.join(sorted(declared))}."
            )

        expected = declared[key]
        if not _matches(value, expected):
            wanted = getattr(expected, "__name__", None) or str(expected)
            raise PolicyLoadError(
                f"{source}: '{section}.{key}' must be a {wanted}, got {type(value).__name__} ({value!r})."
            )

        setattr(target, key, value)

    def get_cached(self) -> ReviewPolicy | None:
        """The policy from the last successful load, if there was one."""
        return self._cached_policy

    def to_yaml(self, policy: ReviewPolicy) -> str:
        """Serialises a policy back to YAML, for generating a starter file."""
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


def load_policy(policy_path: str | None = None) -> ReviewPolicy:
    """Loads a policy: the common case, without constructing a loader."""
    return ReviewPolicyLoader().load(policy_path)


def get_default_policy() -> ReviewPolicy:
    """The policy that applies when no file and no overrides are found."""
    return ReviewPolicy()
