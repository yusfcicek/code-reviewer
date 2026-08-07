"""
Review Triage - Akıllı Review Karar Sistemi.

Değişikliğin önemine göre review seviyesi belirler.
Model'i gereksiz yere zorlamaz - trivial değişiklikleri atlar.
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from .policy import ReviewPolicy


class ReviewDecision(Enum):
    """Review kararı seviyeleri."""

    SKIP = "skip"  # Trivial değişiklik, review gereksiz
    AUTO_APPROVE = "auto"  # Düşük risk, otomatik onay
    QUICK_SCAN = "quick"  # Hızlı tarama yeterli
    FULL_REVIEW = "full"  # Tam detaylı review
    CRITICAL = "critical"  # Acil inceleme, blocking


@dataclass
class TriageResult:
    """Triage sonucu."""

    decision: ReviewDecision
    reason: str
    confidence: float = 1.0  # 0.0 - 1.0
    should_notify: bool = False
    details: dict = field(default_factory=dict)


class ReviewTriage:
    """
    Değişikliğin önemine göre review seviyesi belirler.

    Karar Sırası:
    1. Dosya pattern'i SKIP mi? -> SKIP
    2. Security-critical pattern var mı? -> CRITICAL
    3. Public API değişikliği mi? -> CRITICAL
    4. Sadece yorum/whitespace mi? -> AUTO_APPROVE
    5. Çok az değişiklik mi (<=10 satır)? -> AUTO_APPROVE
    6. Orta seviye değişiklik mi (<=50 satır)? -> QUICK_SCAN
    7. Default -> FULL_REVIEW
    """

    def __init__(self, policy: ReviewPolicy | None = None):
        # Avoid circular import, accept object with matching interface
        self.policy = policy
        self._compile_patterns()

    def _compile_patterns(self):
        """Regex pattern'lerini compile eder."""
        # Triage patterns
        skip_patterns = []
        if self.policy and hasattr(self.policy, "triage"):
            skip_patterns = self.policy.triage.skip_patterns
        else:
            # Default fallback
            skip_patterns = [r"\.md$", r"\.txt$"]

        self._skip_patterns = [re.compile(p, re.IGNORECASE) for p in skip_patterns]

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
            r"^-\s*def\s+\w+\s*\(",  # Fonksiyon kaldırıldı
            r"^-\s*class\s+\w+",  # Sınıf kaldırıldı
            r"^-\s*@api\.",  # API decorator kaldırıldı
            r"BREAKING",  # Breaking change comment
        ]
        self._api_patterns = [re.compile(p, re.MULTILINE) for p in self.api_change_patterns]

    def decide(self, diff: str, file_path: str, full_content: str = None) -> TriageResult:
        """
        Hangi seviye review gerektiğine karar verir.

        Args:
            diff: Git diff içeriği
            file_path: Dosya yolu
            full_content: Dosyanın tam içeriği (opsiyonel)

        Returns:
            TriageResult: Karar ve gerekçe
        """
        # 1. Dosya pattern'i SKIP mi?
        if self._should_skip_file(file_path):
            return TriageResult(
                decision=ReviewDecision.SKIP,
                reason=f"File type skipped by policy: {file_path}",
                confidence=1.0,
                details={"pattern": "skip_file_type"},
            )

        # Diff'i parse et
        added_lines, removed_lines = self._parse_diff_lines(diff)
        total_changes = len(added_lines) + len(removed_lines)

        # 2. Security-critical pattern var mı?
        #
        # Yalnızca eklenen satırlara bakılır. Tüm diff taranınca, değişmemiş
        # context satırlarındaki bir `password` bile dosyayı CRITICAL'a
        # yükseltiyordu; triage'ın var oluş amacı olan maliyet tasarrufu tam
        # tersine dönüyordu (F-09). Tehlikeli bir çağrının *silinmesi* de
        # dosyayı riskli yapmaz.
        critical_match = self._check_critical_patterns("\n".join(added_lines))
        if critical_match:
            return TriageResult(
                decision=ReviewDecision.CRITICAL,
                reason=f"Security-sensitive pattern detected: '{critical_match}'",
                confidence=0.95,
                should_notify=True,
                details={"pattern": critical_match, "type": "security"},
            )

        # 3. Public API değişikliği mi?
        api_match = self._check_api_changes(diff)
        if api_match:
            return TriageResult(
                decision=ReviewDecision.CRITICAL,
                reason=f"Public API change detected: {api_match}",
                confidence=0.90,
                should_notify=True,
                details={"pattern": api_match, "type": "api_change"},
            )

        # Policy configs
        triage_cfg = self.policy.triage if self.policy else None
        allow_comments = triage_cfg.allow_only_comments if triage_cfg else True
        allow_formatting = triage_cfg.allow_only_formatting if triage_cfg else True
        allow_test = triage_cfg.allow_test_files if triage_cfg else True
        max_lines_auto = triage_cfg.max_lines_for_auto if triage_cfg else 10
        max_lines_quick = triage_cfg.max_lines_for_quick if triage_cfg else 50

        # 4. Sadece yorum/whitespace mi?
        if allow_comments and self._is_only_comments(added_lines, removed_lines):
            return TriageResult(
                decision=ReviewDecision.AUTO_APPROVE,
                reason="Only comment/documentation changes",
                confidence=0.95,
                details={"type": "comments_only"},
            )

        # 5. Sadece formatting mi?
        if allow_formatting and self._is_only_formatting(added_lines, removed_lines):
            return TriageResult(
                decision=ReviewDecision.AUTO_APPROVE,
                reason="Only formatting/whitespace changes",
                confidence=0.95,
                details={"type": "formatting_only"},
            )

        # 6. Test dosyası mı ve izin veriliyor mu?
        if allow_test and self._is_test_file(file_path):
            if total_changes <= max_lines_quick:
                return TriageResult(
                    decision=ReviewDecision.QUICK_SCAN,
                    reason=f"Test file with {total_changes} lines changed",
                    confidence=0.85,
                    details={"type": "test_file", "lines": total_changes},
                )

        # 7. Çok az değişiklik mi?
        if total_changes <= max_lines_auto:
            # Logic değişikliği var mı kontrol et
            if not self._has_logic_change(added_lines, removed_lines):
                return TriageResult(
                    decision=ReviewDecision.AUTO_APPROVE,
                    reason=f"Minimal change ({total_changes} lines), no logic change",
                    confidence=0.80,
                    details={"type": "minimal_change", "lines": total_changes},
                )

        # 8. Orta seviye değişiklik mi?
        if total_changes <= max_lines_quick:
            return TriageResult(
                decision=ReviewDecision.QUICK_SCAN,
                reason=f"Moderate change ({total_changes} lines)",
                confidence=0.85,
                details={"type": "moderate_change", "lines": total_changes},
            )

        # 9. Default: Full review
        return TriageResult(
            decision=ReviewDecision.FULL_REVIEW,
            reason=f"Significant change ({total_changes} lines)",
            confidence=0.90,
            details={"type": "significant_change", "lines": total_changes},
        )

    def _should_skip_file(self, file_path: str) -> bool:
        """Dosya skip edilmeli mi?"""
        for pattern in self._skip_patterns:
            if pattern.search(file_path):
                return True
        return False

    def _parse_diff_lines(self, diff: str) -> tuple[list[str], list[str]]:
        """Diff'ten eklenen ve çıkarılan satırları ayırır."""
        added = []
        removed = []

        for line in diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:])

        return added, removed

    def _check_critical_patterns(self, diff: str) -> str | None:
        """Güvenlik-kritik pattern kontrolü."""
        for pattern in self._critical_patterns:
            match = pattern.search(diff)
            if match:
                return match.group(0)
        return None

    def _check_api_changes(self, diff: str) -> str | None:
        """Public API değişiklik kontrolü."""
        for pattern in self._api_patterns:
            match = pattern.search(diff)
            if match:
                return match.group(0)
        return None

    def _is_only_comments(self, added: list[str], removed: list[str]) -> bool:
        """Sadece yorum değişikliği mi?"""
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
        """Sadece formatting değişikliği mi?"""
        if not added or not removed:
            return False

        # Whitespace'i kaldırarak karşılaştır
        added_normalized = [re.sub(r"\s+", "", line) for line in added]
        removed_normalized = [re.sub(r"\s+", "", line) for line in removed]

        # Sıralayıp karşılaştır (formatting değişikliği sonucu aynı olmalı)
        return sorted(added_normalized) == sorted(removed_normalized)

    def _is_test_file(self, file_path: str) -> bool:
        """Test dosyası mı?"""
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
        """Mantık değişikliği var mı?"""
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
            # Yorumları atla
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue

            for pattern in logic_patterns:
                if re.search(pattern, line):
                    return True

        return False

    def batch_decide(self, changes: list[dict]) -> list[tuple[str, TriageResult]]:
        """
        Birden fazla değişiklik için toplu karar.

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
        """Triage sonuçlarının özeti."""
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
    Convenience function - değişiklikleri triage eder.

    Eskiden bir ``TriageConfig`` alıyordu; ``ReviewTriage`` ise
    ``policy.triage``/``policy.security`` arıyordu, dolayısıyla verilen config
    sessizce yok sayılıp iki sabit pattern'e düşülüyordu (F-18, F-30).

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
