"""Review policy: the rules a team agrees to enforce.

These are plain dataclasses with defaults. Reading them from YAML or from the
environment is a loader's job and lives in the infrastructure layer — the
domain receives a populated ``ReviewPolicy`` and never learns where it came
from.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


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
