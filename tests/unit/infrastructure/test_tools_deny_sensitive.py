"""The deny-list has to hold at the tool boundary, not only inside Workspace.

Every one of these tools is reachable by the model, and the model's input is
the diff. A tool that walks the tree itself instead of asking the workspace has
its own copy of the rules — and its own copy is the one that will be out of
date (finding G-05).
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from code_reviewer.infrastructure.tools.definitions import (
    AnalyzerTools,
    CodeSearchTools,
    DependencyAnalysisTools,
    FileSystemTools,
    SmartFileTools,
    set_workspace,
)
from code_reviewer.infrastructure.tools.workspace import Workspace


class _Checkout:
    """What a CI runner's checkout actually contains."""

    def __enter__(self):
        self._temporary = TemporaryDirectory()
        self.root = Path(self._temporary.name) / "repo"
        (self.root / "src").mkdir(parents=True)
        (self.root / "keys").mkdir()

        (self.root / "src" / "app.py").write_text("import os\nvalue = 1\n", encoding="utf-8")
        (self.root / ".env").write_text("GITLAB_TOKEN=glpat-realsecret\n", encoding="utf-8")
        (self.root / "keys" / "id_rsa").write_text("PRIVATE-KEY-BODY\n", encoding="utf-8")

        set_workspace(Workspace(self.root))
        return self

    def __exit__(self, *exc_info):
        set_workspace(None)
        self._temporary.cleanup()
        return False


class TestSensitiveFilesAreNotReadable(unittest.TestCase):
    def test_read_file_refuses_a_credential_file(self):
        with _Checkout():
            result = FileSystemTools.read_file(".env")

            self.assertTrue(result.startswith("Refused:"))
            self.assertNotIn("glpat-realsecret", result)

    def test_read_file_refuses_a_private_key(self):
        with _Checkout():
            result = FileSystemTools.read_file("keys/id_rsa")

            self.assertTrue(result.startswith("Refused:"))
            self.assertNotIn("PRIVATE-KEY-BODY", result)

    def test_reading_an_ordinary_file_still_works(self):
        with _Checkout():
            self.assertIn("value = 1", FileSystemTools.read_file("src/app.py"))


class TestSensitiveFilesAreNotDiscoverable(unittest.TestCase):
    """Locating one is the first half of reading one."""

    def test_a_listing_omits_them(self):
        with _Checkout():
            listing = FileSystemTools.list_files(".")

            self.assertIn("src/app.py", listing)
            self.assertNotIn(".env", listing)
            self.assertNotIn("id_rsa", listing)

    def test_find_file_does_not_surface_them(self):
        # Asserted on "no match", not on the absence of the substring: the
        # not-found message echoes the query back, so a substring check would
        # pass for the wrong reason.
        with _Checkout():
            for query in ("env", "id_rsa"):
                with self.subTest(query=query):
                    self.assertIn("No file found", SmartFileTools.find_file(query))

    def test_find_file_still_finds_ordinary_files(self):
        with _Checkout():
            self.assertIn("src/app.py", SmartFileTools.find_file("app"))


class TestSensitiveContentDoesNotLeakThroughOtherTools(unittest.TestCase):
    def test_a_search_does_not_return_lines_from_a_credential_file(self):
        with _Checkout():
            result = CodeSearchTools.grep_search("glpat")

            self.assertNotIn("glpat-realsecret", result)

    def test_symbol_reading_refuses_a_credential_file(self):
        with _Checkout():
            result = SmartFileTools.read_symbol_definition("GITLAB_TOKEN in .env")

            self.assertNotIn("glpat-realsecret", result)

    def test_import_analysis_refuses_a_credential_file(self):
        with _Checkout():
            self.assertTrue(DependencyAnalysisTools.get_file_imports(".env").startswith("Refused:"))

    def test_a_scan_refuses_a_credential_file(self):
        with _Checkout():
            self.assertTrue(AnalyzerTools.run_sast_scan(".env").startswith("Refused:"))


class TestSearchPatternsAreValidated(unittest.TestCase):
    def test_a_flag_shaped_pattern_is_refused(self):
        with _Checkout():
            result = CodeSearchTools.grep_search("--include=.env")

            self.assertTrue(result.startswith("Refused:"))

    def test_the_refusal_explains_itself_to_the_model(self):
        with _Checkout():
            self.assertIn("flag", CodeSearchTools.grep_search("-c"))


if __name__ == "__main__":
    unittest.main()
