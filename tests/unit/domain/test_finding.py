"""Unit tests for the shared finding model.

Every analyzer had its own result type, so a report could not be assembled from
more than one of them and the gate had to recover numbers by parsing the
model's prose (findings F-28, F-32).
"""

import unittest

from code_reviewer.domain.finding import AffectedCode, Finding, FindingCategory
from code_reviewer.domain.severity import Severity


def _finding(severity=Severity.MEDIUM, line=1, **kwargs):
    defaults = {
        "category": FindingCategory.SECURITY,
        "severity": severity,
        "file_path": "src/app.py",
        "line_number": line,
        "title": "Something is wrong",
        "description": "A longer explanation of what is wrong.",
        "remediation": "Do the other thing instead.",
    }
    defaults.update(kwargs)
    return Finding(**defaults)


class TestConstruction(unittest.TestCase):
    def test_location_reads_as_file_and_line(self):
        self.assertEqual(_finding(line=42).location, "src/app.py:42")

    def test_location_without_a_line_is_the_file(self):
        self.assertEqual(_finding(line=0).location, "src/app.py")

    def test_location_without_a_file_is_unknown(self):
        self.assertEqual(_finding(file_path="", line=0).location, "unknown")

    def test_optional_fields_default_to_empty(self):
        finding = _finding()

        self.assertEqual(finding.rule_id, "")
        self.assertEqual(finding.cwe_id, "")
        self.assertEqual(finding.evidence, "")


class TestOrdering(unittest.TestCase):
    def test_findings_sort_by_severity_first(self):
        findings = [_finding(Severity.LOW), _finding(Severity.CRITICAL), _finding(Severity.MEDIUM)]

        self.assertEqual(
            [f.severity for f in sorted(findings)],
            [Severity.CRITICAL, Severity.MEDIUM, Severity.LOW],
        )

    def test_equal_severities_sort_by_location(self):
        findings = [_finding(line=9), _finding(line=2)]

        self.assertEqual([f.line_number for f in sorted(findings)], [2, 9])


class TestSummarising(unittest.TestCase):
    def test_counts_by_severity(self):
        findings = [_finding(Severity.CRITICAL), _finding(Severity.LOW), _finding(Severity.LOW)]

        counts = Finding.count_by_severity(findings)

        self.assertEqual(counts[Severity.CRITICAL], 1)
        self.assertEqual(counts[Severity.LOW], 2)
        self.assertEqual(counts[Severity.HIGH], 0)

    def test_worst_severity_of_an_empty_list_is_info(self):
        self.assertIs(Finding.worst_severity([]), Severity.INFO)

    def test_worst_severity_picks_the_most_severe(self):
        findings = [_finding(Severity.LOW), _finding(Severity.HIGH)]

        self.assertIs(Finding.worst_severity(findings), Severity.HIGH)


class TestAffectedCode(unittest.TestCase):
    def test_identity_is_file_and_symbol(self):
        first = AffectedCode("src/api.py", "handle", "struct changed")
        second = AffectedCode("src/api.py", "handle", "a different reason")

        self.assertEqual(first.identity, second.identity)

    def test_different_symbols_are_different_entries(self):
        first = AffectedCode("src/api.py", "handle", "reason")
        second = AffectedCode("src/api.py", "dispatch", "reason")

        self.assertNotEqual(first.identity, second.identity)

    def test_preview_is_truncated_to_a_readable_length(self):
        entry = AffectedCode("src/api.py", "handle", "reason", preview="x" * 500)

        self.assertEqual(len(entry.preview), AffectedCode.MAX_PREVIEW_CHARS)

    def test_rendering_names_the_symbol_and_the_reason(self):
        entry = AffectedCode("src/api.py", "handle", "struct field renamed", line_number=12)

        rendered = str(entry)

        self.assertIn("src/api.py:12", rendered)
        self.assertIn("handle", rendered)
        self.assertIn("struct field renamed", rendered)


if __name__ == "__main__":
    unittest.main()


class TestFindingIsAValue(unittest.TestCase):
    """Deduplication needs a key, and a key needs to be hashable.

    Two detectors reporting the same problem at the same line under the same
    rule is one problem (finding G-08). Collapsing them needs `Finding` to
    behave as a value: equal by content, usable in a set or as a dict key.
    """

    @staticmethod
    def _finding(**overrides):
        defaults = {
            "category": FindingCategory.SECURITY,
            "severity": Severity.HIGH,
            "file_path": "src/app.py",
            "line_number": 12,
            "title": "SQL Injection",
            "description": "Concatenated query",
            "remediation": "Parameterise it",
            "rule_id": "SAST.SQL_INJECTION",
        }
        return Finding(**{**defaults, **overrides})

    def test_two_identical_findings_are_equal(self):
        self.assertEqual(self._finding(), self._finding())

    def test_identical_findings_hash_alike(self):
        self.assertEqual(len({self._finding(), self._finding()}), 1)

    def test_findings_differing_by_line_are_distinct(self):
        self.assertEqual(len({self._finding(), self._finding(line_number=13)}), 2)

    def test_a_finding_cannot_be_mutated_after_construction(self):
        finding = self._finding()

        with self.assertRaises(Exception):
            finding.severity = Severity.LOW

    def test_the_metrics_mapping_cannot_be_mutated(self):
        """A mutable field inside a value object is a value object in name only."""
        finding = self._finding(metrics={"depth": 3})

        with self.assertRaises(TypeError):
            finding.metrics["depth"] = 4

    def test_metrics_are_still_readable_as_a_mapping(self):
        finding = self._finding(metrics={"depth": 3})

        self.assertEqual(finding.metrics["depth"], 3)
        self.assertEqual(dict(finding.metrics), {"depth": 3})

    def test_findings_with_different_metrics_are_still_hashable(self):
        pair = {self._finding(metrics={"a": 1}), self._finding(metrics={"b": 2})}

        self.assertEqual(len(pair), 2)


class TestRuleNamespace(unittest.TestCase):
    """A bare id has no namespace for a glob to match (finding G-08)."""

    @staticmethod
    def _with_rule(rule_id):
        return Finding(
            category=FindingCategory.SECURITY,
            severity=Severity.LOW,
            file_path="a.py",
            line_number=1,
            title="t",
            description="d",
            remediation="r",
            rule_id=rule_id,
        )

    def test_the_namespace_is_the_segment_before_the_first_dot(self):
        self.assertEqual(self._with_rule("SAST.SQL_INJECTION").namespace, "SAST")

    def test_a_further_dot_does_not_extend_the_namespace(self):
        self.assertEqual(self._with_rule("QUALITY.SOLID.SRP").namespace, "QUALITY")

    def test_an_unnamespaced_id_has_no_namespace(self):
        self.assertEqual(self._with_rule("sql_injection").namespace, "")

    def test_an_absent_id_has_no_namespace(self):
        self.assertEqual(self._with_rule("").namespace, "")
