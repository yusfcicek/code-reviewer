"""Unit tests for the semantic change analyzer.

Three claims the analyzer could not support are pinned here: an empty diff
classified as STYLE because two empty lists compare equal (F-12), BUGFIX
triggered by the substring `fix` inside words like `prefix` (F-13), and
"defined but never called" asserted from single-file visibility (F-14).
"""

import textwrap
import unittest

from openhands.agent.analyzers.semantic_analyzer import (
    ChangeType,
    SemanticChangeAnalyzer,
    analyze_semantic_changes,
)


class TestChangeClassification(unittest.TestCase):
    def setUp(self):
        self.analyzer = SemanticChangeAnalyzer()

    def _classify(self, diff, content=None, path="m.py"):
        return self.analyzer.analyze_diff(diff, content, path).change_type

    def test_empty_diff_is_unknown_not_style(self):
        """Regression for F-12."""
        self.assertIs(self._classify(""), ChangeType.UNKNOWN)

    def test_diff_with_only_context_lines_is_unknown(self):
        """Regression for F-12."""
        diff = "@@ -1,2 +1,2 @@\n unchanged one\n unchanged two\n"

        self.assertIs(self._classify(diff), ChangeType.UNKNOWN)

    def test_whitespace_only_change_is_style(self):
        diff = "-def run( a ):\n+def run(a):\n"

        self.assertIs(self._classify(diff), ChangeType.STYLE)

    def test_comment_only_change_is_documentation(self):
        diff = "+# explains the retry budget\n"

        self.assertIs(self._classify(diff), ChangeType.DOCUMENTATION)

    def test_word_fix_marks_a_bugfix(self):
        diff = "+# fix: guard against an empty queue\n+if not queue:\n+    return None\n"

        self.assertIs(self._classify(diff), ChangeType.BUGFIX)

    def test_prefix_does_not_mark_a_bugfix(self):
        """Regression for F-13."""
        diff = "+prefix = compute_prefix(name)\n+return prefix\n"

        self.assertIsNot(self._classify(diff), ChangeType.BUGFIX)

    def test_debug_does_not_mark_a_bugfix(self):
        """Regression for F-13."""
        diff = "+debugger = Debugger()\n+debugger.attach()\n"

        self.assertIsNot(self._classify(diff), ChangeType.BUGFIX)

    def test_new_function_is_a_feature(self):
        diff = textwrap.dedent(
            """
            +def summarise(rows):
            +    total = 0
            +    for row in rows:
            +        total += row.value
            +    return total
            """
        )

        self.assertIs(self._classify(diff), ChangeType.FEATURE)


class TestIntegrityIssues(unittest.TestCase):
    def test_unreferenced_function_message_states_its_limits(self):
        """Regression for F-14.

        The analyzer only sees one file, so it cannot know whether a function
        is called from elsewhere. The wording has to say what was actually
        checked.
        """
        content = "def helper():\n    return 1\n"
        diff = "+def helper():\n+    return 1\n"

        result = SemanticChangeAnalyzer().analyze_diff(diff, content, "m.py")

        self.assertTrue(result.integrity_issues)
        description = result.integrity_issues[0].description
        self.assertIn("this file", description.lower())
        self.assertNotIn("never called", description.lower())

    def test_function_used_in_the_same_file_is_not_reported(self):
        content = "def helper():\n    return 1\n\nvalue = helper()\n"
        diff = "+def helper():\n+    return 1\n"

        result = SemanticChangeAnalyzer().analyze_diff(diff, content, "m.py")

        self.assertEqual(result.integrity_issues, [])


class TestRiskScore(unittest.TestCase):
    def test_documentation_change_is_low_risk(self):
        result = SemanticChangeAnalyzer().analyze_diff("+# a note\n", None, "m.py")

        self.assertLessEqual(result.risk_score, 20)

    def test_risk_score_is_capped(self):
        diff = "\n".join(f"-def gone_{i}(self):" for i in range(30))

        result = SemanticChangeAnalyzer().analyze_diff(diff, None, "m.py")

        self.assertLessEqual(result.risk_score, 100)


class TestToolWrapper(unittest.TestCase):
    def test_output_names_the_file_and_the_change_type(self):
        rendered = analyze_semantic_changes("+value = 1\n", None, "src/app.py")

        self.assertIn("src/app.py", rendered)
        self.assertIn("Change Type", rendered)


if __name__ == "__main__":
    unittest.main()
