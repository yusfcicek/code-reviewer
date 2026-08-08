"""Unit tests for the dependency tracker's usage classification.

``_classify_usage`` contained

    elif ':' in context and symbol_name in context.split(':')[1] if ':' in context else False

where operator precedence wraps the entire condition in a conditional
expression. The intent could not be recovered from the code and the branch
behaved by accident (finding F-08). Each branch is asserted here so the
classification has a specification.
"""

import unittest
from unittest.mock import MagicMock, patch

from code_reviewer.domain.finding import DependencyType
from code_reviewer.infrastructure.analyzers.dependency import DependencyTracker


class TestClassifyUsage(unittest.TestCase):
    def setUp(self):
        self.tracker = DependencyTracker(".")

    def _classify(self, context, symbol="Target"):
        return self.tracker._classify_usage(context, symbol)

    def test_plain_import(self):
        self.assertIs(self._classify("import Target"), DependencyType.IMPORT)

    def test_from_import(self):
        self.assertIs(self._classify("from package import Target"), DependencyType.IMPORT)

    def test_indented_import(self):
        self.assertIs(self._classify("    import Target"), DependencyType.IMPORT)

    def test_inheritance(self):
        self.assertIs(self._classify("class Child(Target):"), DependencyType.INHERITANCE)

    def test_inheritance_wins_over_call(self):
        """`class Child(Target)` also looks like a call; inheritance is more specific."""
        self.assertIs(self._classify("class Child(Target):"), DependencyType.INHERITANCE)

    def test_direct_call(self):
        self.assertIs(self._classify("result = Target(value)"), DependencyType.DIRECT_CALL)

    def test_call_with_space_before_bracket(self):
        self.assertIs(self._classify("result = Target (value)"), DependencyType.DIRECT_CALL)

    def test_type_annotation(self):
        self.assertIs(self._classify("handler: Target = None"), DependencyType.TYPE_USAGE)

    def test_annotated_parameter(self):
        self.assertIs(self._classify("def run(handler: Target):"), DependencyType.TYPE_USAGE)

    def test_bare_reference_is_a_data_structure_usage(self):
        self.assertIs(self._classify("payload = Target"), DependencyType.DATA_STRUCTURE)

    def test_word_boundaries_are_respected(self):
        """`TargetHelper` is a different symbol and must not read as a call."""
        self.assertIs(self._classify("value = TargetHelper(x)"), DependencyType.DATA_STRUCTURE)


class TestRiskLevels(unittest.TestCase):
    def test_risk_grows_with_the_number_of_affected_files(self):
        tracker = DependencyTracker(".")

        def fake_usages(_symbol):
            from code_reviewer.domain.finding import AffectedCode

            return [
                AffectedCode(
                    file_path=f"file_{i}.py",
                    symbol_name="fn",
                    line_number=1,
                    dependency_type=DependencyType.DIRECT_CALL,
                )
                for i in range(12)
            ]

        tracker._find_all_usages = fake_usages
        report = tracker.track_data_structure_impact("Target")

        self.assertEqual(report.total_affected_files, 12)
        self.assertEqual(report.risk_level, "critical")

    def test_no_usages_is_low_risk(self):
        tracker = DependencyTracker(".")
        tracker._find_all_usages = lambda _symbol: []

        report = tracker.track_data_structure_impact("Unused")

        self.assertEqual(report.risk_level, "low")
        self.assertIn("No usages found", tracker.get_affected_by_struct_change("Unused"))


if __name__ == "__main__":
    unittest.main()


class TestUsageSearchIsSafe(unittest.TestCase):
    """The second `grep` call site, missed when G-06 fixed the first.

    `find_affected_by_change` and `find_ripple_effects` are agent tools, so the
    symbol reaching this search comes from the model, which got it from the
    diff. It was assembled without `--`, without `-F` and without excluding
    credential files — the same three defects G-06 fixed in the tool module,
    in a call site nobody looked at. Ruff's `S603` found it (finding G-18).
    """

    def _command(self, symbol):
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1, stdout="")
            DependencyTracker(root_path=".")._find_all_usages(symbol)
            return run.call_args[0][0] if run.call_args else []

    def test_the_symbol_comes_after_a_separator(self):
        command = self._command("handle_request")

        self.assertIn("--", command)
        self.assertLess(command.index("--"), command.index("handle_request"))

    def test_the_symbol_is_a_fixed_string(self):
        self.assertIn("-F", self._command("handle_request"))

    def test_credential_files_are_excluded(self):
        command = self._command("token")

        self.assertIn("--exclude=.env", command)
        self.assertIn("--exclude=*.pem", command)

    def test_a_flag_shaped_symbol_runs_nothing(self):
        """Refused before a process is started, not sanitised into one."""
        with patch("subprocess.run") as run:
            result = DependencyTracker(root_path=".")._find_all_usages("--include=.env")

        run.assert_not_called()
        self.assertEqual(result, [])

    def test_a_symbol_with_control_characters_runs_nothing(self):
        with patch("subprocess.run") as run:
            DependencyTracker(root_path=".")._find_all_usages("a\nb")

        run.assert_not_called()
