"""Silencing a finding, narrowly and with a reason.

Every static analyzer produces false positives; one that does not is not
looking hard enough. Without a way to suppress, a team facing one misfiring
rule has two options — turn the rule off, or stop the gate blocking — and both
end the tool's usefulness (finding G-07).

What keeps suppression from becoming that second off-switch is its shape: one
line or one file, a named rule, a written reason, and a count that makes every
silence visible.
"""

import unittest

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import (
    SuppressionDirective,
    apply_suppressions,
    parse_directives,
)


def _finding(rule="SAST.SQL_INJECTION", line=1, path="app.py"):
    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.HIGH,
        file_path=path,
        line_number=line,
        title="SQL Injection",
        description="Concatenated query",
        remediation="Parameterise it",
        rule_id=rule,
    )


class TestTrailingDirectives(unittest.TestCase):
    """The comment sits on the line it excuses."""

    SOURCE = 'query = "SELECT " + name  # review-ignore: SAST.SQL_INJECTION - name is an enum\n'

    def test_the_finding_on_that_line_is_suppressed(self):
        result = apply_suppressions([_finding(line=1)], self.SOURCE)

        self.assertEqual(result.findings, [])
        self.assertEqual(len(result.suppressed), 1)

    def test_the_reason_travels_with_it(self):
        result = apply_suppressions([_finding(line=1)], self.SOURCE)

        self.assertEqual(result.suppressed[0].directive.reason, "name is an enum")

    def test_the_finding_itself_is_kept_for_reporting(self):
        """A suppression nobody can see is a rule that never fired."""
        result = apply_suppressions([_finding(line=1)], self.SOURCE)

        self.assertEqual(result.suppressed[0].finding.rule_id, "SAST.SQL_INJECTION")

    def test_a_finding_on_another_line_survives(self):
        result = apply_suppressions([_finding(line=2)], self.SOURCE)

        self.assertEqual(len(result.findings), 1)

    def test_an_unrelated_rule_on_the_same_line_survives(self):
        result = apply_suppressions([_finding(rule="QUALITY.SRP", line=1)], self.SOURCE)

        self.assertEqual(len(result.findings), 1)


class TestStandaloneDirectives(unittest.TestCase):
    """A comment on its own line covers the line below it.

    So a directive can sit above the code it explains rather than trailing a
    line that is already long.
    """

    SOURCE = (
        '# review-ignore: SAST.SQL_INJECTION - reviewed 2026-08, name is an enum\nquery = "SELECT " + name\n'
    )

    def test_the_following_line_is_covered(self):
        result = apply_suppressions([_finding(line=2)], self.SOURCE)

        self.assertEqual(result.findings, [])

    def test_the_comment_line_itself_is_not_covered(self):
        """Otherwise a directive would excuse whatever the comment sits on."""
        result = apply_suppressions([_finding(line=1)], self.SOURCE)

        self.assertEqual(len(result.findings), 1)

    def test_an_indented_standalone_comment_still_counts(self):
        source = "    # review-ignore: SAST.X - reason\n    value = 1\n"

        result = apply_suppressions([_finding(rule="SAST.X", line=2)], source)

        self.assertEqual(result.findings, [])


class TestNamespaceGlobs(unittest.TestCase):
    def test_a_namespace_glob_matches_every_rule_in_it(self):
        source = "value = 1  # review-ignore: SAST.* - vendored third-party source\n"

        for rule in ("SAST.SQL_INJECTION", "SAST.XSS", "SAST.HARDCODED_SECRET"):
            with self.subTest(rule=rule):
                result = apply_suppressions([_finding(rule=rule, line=1)], source)

                self.assertEqual(result.findings, [])

    def test_a_namespace_glob_does_not_reach_other_namespaces(self):
        source = "value = 1  # review-ignore: SAST.* - reason\n"

        result = apply_suppressions([_finding(rule="QUALITY.SRP", line=1)], source)

        self.assertEqual(len(result.findings), 1)

    def test_a_bare_star_is_not_a_valid_rule(self):
        """Suppressing everything is the second off-switch, through another door."""
        source = "value = 1  # review-ignore: * - please stop\n"

        result = apply_suppressions([_finding(line=1)], source)

        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.suppressed, [])

    def test_a_bare_star_yields_no_directive_at_all(self):
        self.assertEqual(parse_directives("x = 1  # review-ignore: * - no\n"), [])


class TestFileScope(unittest.TestCase):
    SOURCE = (
        "# review-ignore-file: SAST.* - vendored, regenerated on every build\nline_two = 1\nline_three = 2\n"
    )

    def test_every_line_is_covered(self):
        findings = [_finding(line=n) for n in (1, 2, 3, 99)]

        result = apply_suppressions(findings, self.SOURCE)

        self.assertEqual(result.findings, [])
        self.assertEqual(len(result.suppressed), 4)

    def test_it_still_respects_the_rule_id(self):
        result = apply_suppressions([_finding(rule="QUALITY.SRP", line=2)], self.SOURCE)

        self.assertEqual(len(result.findings), 1)

    def test_it_can_appear_anywhere_in_the_file(self):
        source = "value = 1\n# review-ignore-file: SAST.X - reason\nother = 2\n"

        result = apply_suppressions([_finding(rule="SAST.X", line=1)], source)

        self.assertEqual(result.findings, [])


class TestReasons(unittest.TestCase):
    def test_a_dash_separates_the_reason(self):
        directives = parse_directives("x = 1  # review-ignore: SAST.X - the reason\n")

        self.assertEqual(directives[0].reason, "the reason")

    def test_an_em_dash_also_separates(self):
        directives = parse_directives("x = 1  # review-ignore: SAST.X — the reason\n")

        self.assertEqual(directives[0].reason, "the reason")

    def test_a_colon_also_separates(self):
        directives = parse_directives("x = 1  # review-ignore: SAST.X: the reason\n")

        self.assertEqual(directives[0].reason, "the reason")

    def test_a_directive_without_a_reason_still_suppresses(self):
        """Refusing would turn a typo into a blocking finding at the worst moment."""
        result = apply_suppressions([_finding(line=1)], "x = 1  # review-ignore: SAST.SQL_INJECTION\n")

        self.assertEqual(result.findings, [])

    def test_a_directive_without_a_reason_is_reported_as_unexplained(self):
        directives = parse_directives("x = 1  # review-ignore: SAST.X\n")

        self.assertEqual(directives[0].reason, "")
        self.assertFalse(directives[0].is_explained)

    def test_a_directive_with_a_reason_is_explained(self):
        directives = parse_directives("x = 1  # review-ignore: SAST.X - because\n")

        self.assertTrue(directives[0].is_explained)


class TestSyntax(unittest.TestCase):
    def test_hash_and_slash_comments_both_parse(self):
        for comment in ("# review-ignore: SAST.X - r", "// review-ignore: SAST.X - r"):
            with self.subTest(comment=comment):
                self.assertEqual(len(parse_directives(f"value = 1  {comment}\n")), 1)

    def test_several_rules_in_one_directive(self):
        directives = parse_directives("x = 1  # review-ignore: SAST.X, QUALITY.SRP - both\n")

        self.assertEqual({d.rule_id for d in directives}, {"SAST.X", "QUALITY.SRP"})

    def test_the_keyword_is_case_insensitive(self):
        self.assertEqual(len(parse_directives("x = 1  # REVIEW-IGNORE: SAST.X - r\n")), 1)

    def test_ordinary_prose_is_not_a_directive(self):
        for line in ("# review this later", "# ignore the warning above", "# reviewignore: X"):
            with self.subTest(line=line):
                self.assertEqual(parse_directives(f"{line}\n"), [])

    def test_empty_source_yields_nothing(self):
        self.assertEqual(parse_directives(""), [])

    def test_source_without_directives_yields_nothing(self):
        self.assertEqual(parse_directives("def handle():\n    return 1\n"), [])


class TestResultShape(unittest.TestCase):
    def test_nothing_suppressed_returns_everything(self):
        findings = [_finding(line=1), _finding(line=2)]

        result = apply_suppressions(findings, "a = 1\nb = 2\n")

        self.assertEqual(result.findings, findings)
        self.assertEqual(result.suppressed, [])

    def test_the_count_is_available(self):
        source = "a = 1  # review-ignore: SAST.SQL_INJECTION - r\n"

        result = apply_suppressions([_finding(line=1), _finding(line=2)], source)

        self.assertEqual(result.suppressed_count, 1)

    def test_empty_findings_are_handled(self):
        result = apply_suppressions([], "# review-ignore-file: SAST.* - r\n")

        self.assertEqual(result.findings, [])
        self.assertEqual(result.suppressed, [])

    def test_empty_source_suppresses_nothing(self):
        findings = [_finding(line=1)]

        self.assertEqual(apply_suppressions(findings, "").findings, findings)

    def test_a_directive_is_a_value(self):
        first = SuppressionDirective(rule_id="SAST.X", reason="r", line=1)
        second = SuppressionDirective(rule_id="SAST.X", reason="r", line=1)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()


class TestWhereTheDirectiveWasWritten(unittest.TestCase):
    """`line` and `target_line` are different questions.

    The report points at `line`, so a reader lands on the sentence explaining
    the silence rather than on the code it excused.
    """

    def test_a_trailing_directive_covers_its_own_line(self):
        directive = parse_directives("x = 1  # review-ignore: SAST.X - r\n")[0]

        self.assertEqual(directive.line, 1)
        self.assertEqual(directive.target_line, 1)

    def test_a_standalone_directive_is_written_above_what_it_covers(self):
        directive = parse_directives("# review-ignore: SAST.X - r\nx = 1\n")[0]

        self.assertEqual(directive.line, 1)
        self.assertEqual(directive.target_line, 2)

    def test_a_file_directive_records_where_it_was_written(self):
        directive = parse_directives("x = 1\n# review-ignore-file: SAST.X - r\n")[0]

        self.assertEqual(directive.line, 2)
        self.assertTrue(directive.file_level)
