"""Triage: deciding how much review a change deserves.

Every file sent to the model costs tokens and wall-clock time. Triage answers
the cheaper question first — does this change need a model at all? — so that a
documentation tweak and a change to an authentication path are not treated
alike.
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from .policy import ReviewPolicy


class ReviewDecision(Enum):
    """How much review a change warrants."""

    SKIP = "skip"  # Not worth reviewing: documentation, generated files
    AUTO_APPROVE = "auto"  # Low risk: comments, formatting, no logic change
    QUICK_SCAN = "quick"  # Moderate change: a scan is enough
    FULL_REVIEW = "full"  # Significant change: full architectural review
    CRITICAL = "critical"  # Security-sensitive, or a public API removal


@dataclass
class TriageResult:
    """One file's triage decision, with the reason for it."""

    decision: ReviewDecision
    reason: str
    confidence: float = 1.0  # 0.0 - 1.0
    should_notify: bool = False
    details: dict = field(default_factory=dict)


class ReviewTriage:
    """
    Decides how much review a change warrants.

    Decision order — the first rule that matches wins:
    1. Does the path match a skip pattern? -> SKIP
    2. Does an added line match a security pattern? -> CRITICAL
    3. Does it remove a public symbol? -> CRITICAL
    4. Is it a manifest or a CI definition? -> FULL_REVIEW
    5. Is it comment- or whitespace-only? -> AUTO_APPROVE
    6. Is it small (<=10 lines) with no logic change? -> AUTO_APPROVE
    7. Is it moderate (<=50 lines)? -> QUICK_SCAN
    8. Default -> FULL_REVIEW

    Rule 4 sits above every size rule because the changes it catches are small
    by nature: a version bump and a `curl … | sh` added to a CI job are both
    one line (finding G-11). It sits below the two CRITICAL rules because
    those are more specific and they notify.
    """

    def __init__(self, policy: ReviewPolicy | None = None):
        # Avoid circular import, accept object with matching interface
        self.policy = policy
        self._compile_patterns()

    def _compile_patterns(self):
        """Compiles the patterns once, so `decide` stays cheap per file."""
        # Triage patterns
        skip_patterns = []
        if self.policy and hasattr(self.policy, "triage"):
            skip_patterns = self.policy.triage.skip_patterns
        else:
            # Default fallback
            skip_patterns = [r"\.md$", r"\.txt$"]

        self._skip_patterns = [re.compile(p, re.IGNORECASE) for p in skip_patterns]

        # Which files a team treats as supply-chain-critical varies, so the
        # list is policy rather than a constant in this module (decision D-5).
        manifest_patterns = []
        if self.policy and hasattr(self.policy, "triage"):
            manifest_patterns = self.policy.triage.manifest_patterns
        self._manifest_patterns = [re.compile(p) for p in manifest_patterns]

        # Critical patterns (Security + API)
        critical_patterns = []
        if self.policy and hasattr(self.policy, "security"):
            critical_patterns.extend(self.policy.security.banned_patterns)
            critical_patterns.extend(self.policy.security.secret_patterns)
        else:
            # Default fallback
            critical_patterns = [r"password", r"secret", r"api[_-]?key"]

        self._critical_patterns = [re.compile(p, re.IGNORECASE) for p in critical_patterns]

        # API Change patterns (Hardcoded for now as they are logic-specific)
        self.api_change_patterns = [
            r"^-\s*def\s+\w+\s*\(",  # a function was removed
            r"^-\s*class\s+\w+",  # a class was removed
            r"^-\s*@api\.",  # an API decorator was removed
            r"BREAKING",  # Breaking change comment
        ]
        self._api_patterns = [re.compile(p, re.MULTILINE) for p in self.api_change_patterns]

    def decide(self, diff: str, file_path: str, full_content: str | None = None) -> TriageResult:
        """
        Decides how much review this file needs.

        Args:
            diff: The unified diff for this file.
            file_path: Path of the file, used for the skip and test rules.
            full_content: The file at the reviewed commit, when it could be read.

        Returns:
            TriageResult: the decision and why it was taken.
        """
        # 1. Does the path match a skip pattern?
        if self._should_skip_file(file_path):
            return TriageResult(
                decision=ReviewDecision.SKIP,
                reason=f"File type skipped by policy: {file_path}",
                confidence=1.0,
                details={"pattern": "skip_file_type"},
            )

        # Parse the diff
        added_lines, removed_lines = self._parse_diff_lines(diff)
        total_changes = len(added_lines) + len(removed_lines)

        # 2. Does an added line match a security pattern?
        #
        # Added lines only. Scanning the whole diff escalated a file to
        # CRITICAL because of a `password` in an unchanged context line, which
        # inverted the cost saving triage exists for (finding F-09). Deleting a
        # dangerous call does not make a file risky either.
        critical_match = self._check_critical_patterns("\n".join(added_lines))
        if critical_match:
            return TriageResult(
                decision=ReviewDecision.CRITICAL,
                reason=f"Security-sensitive pattern detected: '{critical_match}'",
                confidence=0.95,
                should_notify=True,
                details={"pattern": critical_match, "type": "security"},
            )

        # 3. Does it remove a public symbol?
        api_match = self._check_api_changes(diff)
        if api_match:
            return TriageResult(
                decision=ReviewDecision.CRITICAL,
                reason=f"Public API change detected: {api_match}",
                confidence=0.90,
                should_notify=True,
                details={"pattern": api_match, "type": "api_change"},
            )

        # 4. Is it a manifest or a pipeline definition?
        #
        # Above every size rule, because this class of change is small by
        # nature and the logic-change guard below looks for Python and C
        # keywords that no YAML or JSON line contains (finding G-11).
        if self._is_manifest(file_path):
            return TriageResult(
                decision=ReviewDecision.FULL_REVIEW,
                reason=(
                    f"Dependency manifest or pipeline definition: {file_path}. "
                    f"Reviewed in full regardless of size."
                ),
                confidence=1.0,
                details={"type": "manifest", "lines": total_changes},
            )

        # Policy configs
        triage_cfg = self.policy.triage if self.policy else None
        allow_comments = triage_cfg.allow_only_comments if triage_cfg else True
        allow_formatting = triage_cfg.allow_only_formatting if triage_cfg else True
        allow_test = triage_cfg.allow_test_files if triage_cfg else True
        max_lines_auto = triage_cfg.max_lines_for_auto if triage_cfg else 10
        max_lines_quick = triage_cfg.max_lines_for_quick if triage_cfg else 50

        # 5. Comment- or whitespace-only?
        if allow_comments and self._is_only_comments(added_lines, removed_lines):
            return TriageResult(
                decision=ReviewDecision.AUTO_APPROVE,
                reason="Only comment/documentation changes",
                confidence=0.95,
                details={"type": "comments_only"},
            )

        # 5b. Formatting-only?
        if allow_formatting and self._is_only_formatting(added_lines, removed_lines):
            return TriageResult(
                decision=ReviewDecision.AUTO_APPROVE,
                reason="Only formatting/whitespace changes",
                confidence=0.95,
                details={"type": "formatting_only"},
            )

        # 6. A test file, if the policy treats those more leniently
        if allow_test and self._is_test_file(file_path):
            if total_changes <= max_lines_quick:
                return TriageResult(
                    decision=ReviewDecision.QUICK_SCAN,
                    reason=f"Test file with {total_changes} lines changed",
                    confidence=0.85,
                    details={"type": "test_file", "lines": total_changes},
                )

        # 6b. Small enough to approve without a model?
        if total_changes <= max_lines_auto:
            # ...but only when nothing about the logic moved
            if not self._has_logic_change(added_lines, removed_lines):
                return TriageResult(
                    decision=ReviewDecision.AUTO_APPROVE,
                    reason=f"Minimal change ({total_changes} lines), no logic change",
                    confidence=0.80,
                    details={"type": "minimal_change", "lines": total_changes},
                )

        # 7. Moderate size: a scan rather than a full review
        if total_changes <= max_lines_quick:
            return TriageResult(
                decision=ReviewDecision.QUICK_SCAN,
                reason=f"Moderate change ({total_changes} lines)",
                confidence=0.85,
                details={"type": "moderate_change", "lines": total_changes},
            )

        # 8. Default: full review
        return TriageResult(
            decision=ReviewDecision.FULL_REVIEW,
            reason=f"Significant change ({total_changes} lines)",
            confidence=0.90,
            details={"type": "significant_change", "lines": total_changes},
        )

    def _should_skip_file(self, file_path: str) -> bool:
        """True when the policy says this path is not worth reviewing."""
        return any(pattern.search(file_path) for pattern in self._skip_patterns)

    def _is_manifest(self, file_path: str) -> bool:
        """True when the path names a dependency manifest or a CI definition."""
        return any(pattern.search(file_path) for pattern in self._manifest_patterns)

    def _parse_diff_lines(self, diff: str) -> tuple[list[str], list[str]]:
        """Splits a diff into its added and removed lines."""
        added = []
        removed = []

        for line in diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:])

        return added, removed

    def _check_critical_patterns(self, diff: str) -> str | None:
        """Returns the first security pattern an added line matches."""
        for pattern in self._critical_patterns:
            match = pattern.search(diff)
            if match:
                return match.group(0)
        return None

    def _check_api_changes(self, diff: str) -> str | None:
        """Returns the first public-API removal the diff contains."""
        for pattern in self._api_patterns:
            match = pattern.search(diff)
            if match:
                return match.group(0)
        return None

    def _is_only_comments(self, added: list[str], removed: list[str]) -> bool:
        """True when every changed line is a comment or blank."""
        comment_patterns = [
            r"^\s*#",  # Python comment
            r"^\s*//",  # C/JS comment
            r"^\s*/\*",  # C block comment start
            r"^\s*\*",  # C block comment middle
            r"^\s*\*/",  # C block comment end
            r'^\s*"""',  # Python docstring
            r"^\s*'''",  # Python docstring
            r"^\s*<!--",  # HTML comment
            r"^\s*$",  # Empty line
        ]

        all_lines = added + removed
        if not all_lines:
            return True

        for line in all_lines:
            is_comment = any(re.match(p, line) for p in comment_patterns)
            if not is_comment:
                return False

        return True

    def _is_only_formatting(self, added: list[str], removed: list[str]) -> bool:
        """True when the change only moves whitespace around."""
        if not added or not removed:
            return False

        # Compare with all whitespace stripped...
        added_normalized = [re.sub(r"\s+", "", line) for line in added]
        removed_normalized = [re.sub(r"\s+", "", line) for line in removed]

        # ...and order-independently: a pure reformat leaves the same set.
        return sorted(added_normalized) == sorted(removed_normalized)

    def _is_test_file(self, file_path: str) -> bool:
        """True for paths that look like test files."""
        test_patterns = [
            r"test[s]?/",
            r"_test\.",
            r"test_\w+\.",
            r"\.test\.",
            r"spec\.",
            r"\.spec\.",
        ]
        return any(re.search(p, file_path, re.IGNORECASE) for p in test_patterns)

    def _has_logic_change(self, added: list[str], removed: list[str]) -> bool:
        """True when a changed line touches control flow or a definition."""
        logic_patterns = [
            r"\bif\b",
            r"\belse\b",
            r"\bfor\b",
            r"\bwhile\b",
            r"\breturn\b",
            r"\braise\b",
            r"\btry\b",
            r"\bexcept\b",
            r"\bclass\b",
            r"\bdef\b",
            r"[+\-*/]=",  # Arithmetic assignment
            r"==|!=|<=|>=",  # Comparisons
            r"\band\b|\bor\b",  # Logical operators
        ]

        all_lines = added + removed
        for line in all_lines:
            # Comments cannot change logic
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            for pattern in logic_patterns:
                if re.search(pattern, line):
                    return True

        return False

    def batch_decide(self, changes: list[dict]) -> list[tuple[str, TriageResult]]:
        """
        Triages every change in one merge request.

        Args:
            changes: [{"new_path": str, "diff": str, "full_content": str}, ...]

        Returns:
            List[Tuple[file_path, TriageResult]]
        """
        results = []

        for change in changes:
            file_path = change.get("new_path", "")
            diff = change.get("diff", "")
            full_content = change.get("full_content")

            result = self.decide(diff, file_path, full_content)
            results.append((file_path, result))

        return results

    def get_review_summary(self, results: list[tuple[str, TriageResult]]) -> str:
        """A markdown summary of how the files were triaged."""
        counts = dict.fromkeys(ReviewDecision, 0)

        for _, result in results:
            counts[result.decision] += 1

        summary = ["## 📊 Review Triage Summary\n"]
        summary.append(f"- **SKIP** (trivial): {counts[ReviewDecision.SKIP]}")
        summary.append(f"- **AUTO_APPROVE** (low risk): {counts[ReviewDecision.AUTO_APPROVE]}")
        summary.append(f"- **QUICK_SCAN**: {counts[ReviewDecision.QUICK_SCAN]}")
        summary.append(f"- **FULL_REVIEW**: {counts[ReviewDecision.FULL_REVIEW]}")
        summary.append(f"- **CRITICAL** (blocking): {counts[ReviewDecision.CRITICAL]}")

        needs_review = (
            counts[ReviewDecision.QUICK_SCAN]
            + counts[ReviewDecision.FULL_REVIEW]
            + counts[ReviewDecision.CRITICAL]
        )
        summary.append(f"\n**Model Review Required**: {needs_review} files")

        return "\n".join(summary)


def triage_changes(
    changes: list[dict], policy: ReviewPolicy | None = None
) -> tuple[list[dict], list[dict], str]:
    """
    Convenience wrapper that triages a list of changes.

    It used to take a ``TriageConfig`` while ``ReviewTriage`` looked for
    ``policy.triage`` and ``policy.security``, so the config passed in was
    silently ignored and two hard-coded patterns were used instead
    (findings F-18, F-30).

    Returns:
        Tuple[needs_review, auto_approved, summary]
    """
    triage = ReviewTriage(policy)
    results = triage.batch_decide(changes)

    needs_review = []
    auto_approved = []

    for file_path, result in results:
        change = next((c for c in changes if c.get("new_path") == file_path), None)
        if not change:
            continue

        change["triage_result"] = result

        if result.decision in [
            ReviewDecision.QUICK_SCAN,
            ReviewDecision.FULL_REVIEW,
            ReviewDecision.CRITICAL,
        ]:
            needs_review.append(change)
        elif result.decision == ReviewDecision.AUTO_APPROVE:
            auto_approved.append(change)
        # SKIP olanlar listeye eklenmez

    summary = triage.get_review_summary(results)

    return needs_review, auto_approved, summary
