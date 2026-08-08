"""Review policy: the rules a team agrees to enforce.

These are plain dataclasses with defaults. Reading them from YAML or from the
environment is a loader's job and lives in the infrastructure layer — the
domain receives a populated ``ReviewPolicy`` and never learns where it came
from.
"""

from dataclasses import dataclass, field
from typing import Any

#: Files worth skipping: prose a reviewer reads anyway, and machine-generated
#: lock files that are enormous and contain nothing a human would act on.
#:
#: Deliberately *not* skipped: Dockerfiles, pipeline definitions, Kubernetes
#: manifests, Terraform and dependency manifests. Earlier defaults excluded
#: every `.yaml`, `.json` and `Dockerfile`, which is precisely where privilege
#: escalation, a changed base image or a swapped dependency hides (F-22).
DEFAULT_SKIP_PATTERNS = [
    # Documentation
    r".*\.md$",
    r".*\.txt$",
    r".*\.rst$",
    r".*\.adoc$",
    r"^LICENSE",
    r"^CHANGELOG",
    r"^AUTHORS",
    # Repository metadata
    r"\.gitignore$",
    r"\.gitattributes$",
    r"\.editorconfig$",
    r"\.dockerignore$",
    # Generated lock files
    r"(^|/)uv\.lock$",
    r"(^|/)poetry\.lock$",
    r"(^|/)Pipfile\.lock$",
    r"(^|/)package-lock\.json$",
    r"(^|/)yarn\.lock$",
    r"(^|/)pnpm-lock\.yaml$",
    r"(^|/)Cargo\.lock$",
    r"(^|/)composer\.lock$",
    r"(^|/)Gemfile\.lock$",
    r"(^|/)go\.sum$",
    # Binary and vendored content
    r"\.(png|jpe?g|gif|svg|ico|pdf|woff2?|ttf|eot)$",
    r"(^|/)vendor/",
    r"(^|/)node_modules/",
    r"(^|/)\.min\.(js|css)$",
]


@dataclass
class TriagePolicy:
    """Which files are reviewed, and how much review each one warrants."""

    skip_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_PATTERNS))
    max_lines_for_auto: int = 10
    max_lines_for_quick: int = 50
    allow_only_comments: bool = True
    allow_only_formatting: bool = True
    allow_test_files: bool = True


@dataclass
class SecurityPolicy:
    """What counts as a security problem, and what blocks on it."""

    block_on_critical: bool = True
    block_on_high: bool = True
    block_on_medium: bool = False

    banned_patterns: list[str] = field(
        default_factory=lambda: [r"eval\s*\(", r"exec\s*\(", r"pickle\.loads", r"shell=True"]
    )

    secret_patterns: list[str] = field(
        default_factory=lambda: [
            r"password\s*=\s*['\"][^'\"]+['\"]",
            r"api[_-]?key\s*=",
            r"-----BEGIN.*PRIVATE KEY-----",
        ]
    )


@dataclass
class QualityPolicy:
    """Thresholds the quality analyzer enforces."""

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
    """Which performance rule families run, and at what threshold."""

    alert_on_n_squared: bool = True
    alert_on_n_plus_one: bool = True
    alert_on_memory_leak: bool = True
    max_nested_loops: int = 3


@dataclass
class GatePolicy:
    """How findings and scores translate into a pipeline verdict."""

    #: Severity at or above which an analyzer finding fails the pipeline.
    #: Defaults to CRITICAL only, so switching the gate onto findings does not
    #: silently start failing pipelines that used to pass.
    blocking_severity: str = "critical"

    quality_score_threshold: int = 60
    security_score_threshold: int = 70
    performance_score_threshold: int = 50

    fail_pipeline_on_critical: bool = True
    fail_pipeline_on_quality_below: int = 50

    #: Whether a file the reviewer could not process fails the pipeline.
    #: Defaults to False so a flaky model endpoint does not block merges, but
    #: the failure is always reported in the comment (decision D-4).
    fail_on_review_error: bool = False

    #: A file whose static analysis could not run at all.
    #:
    #: Defaults to True, and the asymmetry with `fail_on_review_error` above is
    #: deliberate. That one covers "the reviewer crashed on this file", where
    #: the model is allowed to fail and the analysis still happened. This one
    #: covers "we could not look", where zero findings means nothing was
    #: examined rather than nothing was found — and for a gate, "unknown" must
    #: not mean "pass" (finding G-09).
    fail_pipeline_on_analysis_error: bool = True

    # Notification
    notify_on_critical: bool = True
    notify_channels: list[str] = field(default_factory=list)


@dataclass
class ReviewPolicy:
    """The complete set of rules one review runs under."""

    version: str = "1.0"

    triage: TriagePolicy = field(default_factory=TriagePolicy)
    security: SecurityPolicy = field(default_factory=SecurityPolicy)
    quality: QualityPolicy = field(default_factory=QualityPolicy)
    performance: PerformancePolicy = field(default_factory=PerformancePolicy)
    gate: GatePolicy = field(default_factory=GatePolicy)

    # Custom overrides
    custom_rules: dict[str, Any] = field(default_factory=dict)
