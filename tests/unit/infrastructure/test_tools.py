"""Unit tests for the agent's tools.

Every tool that touches disk goes through a :class:`Workspace`, so a path the
model produced — which ultimately comes from the diff under review — cannot
reach outside the repository (finding F-21).

Refusals are returned to the model as text rather than raised: the review
should continue with the model told why it cannot have the file.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from code_reviewer.infrastructure.tools.definitions import (
    AnalyzerTools,
    CodeSearchTools,
    DependencyAnalysisTools,
    FileSystemTools,
    SmartFileTools,
    get_tools,
    set_workspace,
)
from code_reviewer.infrastructure.tools.workspace import Workspace


class _Sandbox:
    def __enter__(self):
        self._outer = TemporaryDirectory()
        root = Path(self._outer.name) / "repo"
        (root / "src").mkdir(parents=True)
        (root / "src" / "app.py").write_text(
            "import os\n\n\ndef handle(request):\n    return os.getcwd()\n", encoding="utf-8"
        )
        (Path(self._outer.name) / "secret.txt").write_text("TOP-SECRET\n", encoding="utf-8")
        self.root = root
        set_workspace(Workspace(root))
        return self

    def __exit__(self, *exc_info):
        set_workspace(None)
        self._outer.cleanup()
        return False

    @property
    def outside(self) -> str:
        return str(Path(self._outer.name) / "secret.txt")


class TestReadFile(unittest.TestCase):
    def test_a_file_inside_the_workspace_is_returned(self):
        with _Sandbox():
            self.assertIn("def handle", FileSystemTools.read_file("src/app.py"))

    def test_an_absolute_path_outside_is_refused(self):
        with _Sandbox():
            result = FileSystemTools.read_file("/etc/passwd")

            self.assertIn("outside the workspace", result)

    def test_the_refused_content_is_not_returned(self):
        with _Sandbox() as sandbox:
            result = FileSystemTools.read_file(sandbox.outside)

            self.assertNotIn("TOP-SECRET", result)

    def test_traversal_is_refused(self):
        with _Sandbox():
            result = FileSystemTools.read_file("../secret.txt")

            self.assertIn("outside the workspace", result)

    def test_a_symlink_pointing_outside_is_refused(self):
        with _Sandbox() as sandbox:
            os.symlink(sandbox.outside, sandbox.root / "escape.txt")

            result = FileSystemTools.read_file("escape.txt")

            self.assertNotIn("TOP-SECRET", result)

    def test_a_missing_file_reports_that_it_is_missing(self):
        with _Sandbox():
            self.assertIn("not found", FileSystemTools.read_file("src/absent.py").lower())


class TestListFiles(unittest.TestCase):
    def test_listing_inside_the_workspace_works(self):
        with _Sandbox():
            self.assertIn("app.py", FileSystemTools.list_files("src"))

    def test_listing_outside_is_refused(self):
        with _Sandbox():
            self.assertIn("outside the workspace", FileSystemTools.list_files("/etc"))


class TestGrepSearch(unittest.TestCase):
    def test_matches_inside_the_workspace_are_found(self):
        with _Sandbox():
            self.assertIn("app.py", CodeSearchTools.grep_search("handle"))

    def test_search_outside_is_refused(self):
        with _Sandbox():
            self.assertIn("outside the workspace", CodeSearchTools.grep_search("root", "/etc"))

    def test_no_match_says_so(self):
        with _Sandbox():
            self.assertIn("No matches", CodeSearchTools.grep_search("definitely_absent_symbol"))


class TestFindFile(unittest.TestCase):
    def test_a_file_in_the_workspace_is_located(self):
        with _Sandbox():
            self.assertIn("app.py", SmartFileTools.find_file("app.py"))

    def test_search_does_not_escape_the_workspace(self):
        with _Sandbox():
            result = SmartFileTools.find_file("secret.txt")

            self.assertNotIn("TOP-SECRET", result)
            self.assertIn("No file found", result)


class TestSymbolDefinition(unittest.TestCase):
    def test_a_symbol_inside_the_workspace_is_read(self):
        with _Sandbox():
            result = SmartFileTools.read_symbol_definition("handle in src/app.py")

            self.assertIn("def handle", result)

    def test_a_symbol_outside_the_workspace_is_refused(self):
        with _Sandbox() as sandbox:
            result = SmartFileTools.read_symbol_definition(f"SECRET in {sandbox.outside}")

            self.assertNotIn("TOP-SECRET", result)


class TestDependencyTools(unittest.TestCase):
    def test_imports_of_a_confined_file_are_listed(self):
        with _Sandbox():
            self.assertIn("import os", DependencyAnalysisTools.get_file_imports("src/app.py"))

    def test_imports_outside_the_workspace_are_refused(self):
        with _Sandbox():
            result = DependencyAnalysisTools.get_file_imports("/etc/hosts")

            self.assertIn("outside the workspace", result)

    def test_reference_search_stays_inside_the_workspace(self):
        with _Sandbox():
            result = DependencyAnalysisTools.find_references("handle")

            self.assertIn("app.py", result)


class TestAnalyzerTools(unittest.TestCase):
    def test_sast_scan_of_a_confined_file_runs(self):
        with _Sandbox():
            self.assertIn("SAST", AnalyzerTools.run_sast_scan("src/app.py"))

    def test_sast_scan_outside_the_workspace_is_refused(self):
        with _Sandbox():
            self.assertIn("outside the workspace", AnalyzerTools.run_sast_scan("/etc/hosts"))

    def test_quality_check_outside_the_workspace_is_refused(self):
        with _Sandbox():
            self.assertIn("outside the workspace", AnalyzerTools.check_code_quality("/etc/hosts"))

    def test_performance_check_outside_the_workspace_is_refused(self):
        with _Sandbox():
            self.assertIn("outside the workspace", AnalyzerTools.analyze_performance("/etc/hosts"))


class TestCatalogue(unittest.TestCase):
    def test_every_tool_has_a_name_and_a_description(self):
        for tool in get_tools():
            with self.subTest(tool=tool.name):
                self.assertTrue(tool.name)
                self.assertTrue(tool.description)

    def test_tool_names_are_unique(self):
        names = [tool.name for tool in get_tools()]

        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
