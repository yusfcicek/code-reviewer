"""Checks on the repository's documentation.

Two things this guards.

The source used to carry Turkish docstrings in ten modules while the README,
CONTRIBUTING, the commit messages and the newer code were English, so a reader
hit the boundary mid-file. Several of those comments also described behaviour
that Levels 1-5 changed, which made them wrong as well as inconsistent (F-54).

And a link that no longer resolves is a document that quietly stops being read.
"""

import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY / "code_reviewer"

#: Characters that exist in Turkish and not in English. Emoji and typographic
#: dashes are deliberately not included: the review output uses both.
TURKISH_CHARACTERS = set("şğıçöüŞĞİÇÖÜ")

#: Words common enough in the previous comments to catch a relapse that happens
#: to avoid the special characters.
TURKISH_WORDS = {
    "için",
    "eder",
    "yapar",
    "döner",
    "kontrol",
    "değil",
    "olarak",
    "sonra",
    "sayısı",
    "dosya",
    "kod",
    "hata",
    "bulur",
    "ekler",
    "gerekir",
    "veya",
    "ancak",
}

DOCUMENTS = {
    "README.md": REPOSITORY / "README.md",
    "CONTRIBUTING.md": REPOSITORY / "CONTRIBUTING.md",
    "SECURITY.md": REPOSITORY / "SECURITY.md",
    "CHANGELOG.md": REPOSITORY / "CHANGELOG.md",
    "ARCHITECTURE.md": REPOSITORY / "docs" / "ARCHITECTURE.md",
    "ADR index": REPOSITORY / "docs" / "adr" / "README.md",
}


def _markdown_files():
    for path in REPOSITORY.rglob("*.md"):
        if any(part in {".venv", "node_modules", ".git"} for part in path.parts):
            continue
        yield path


class TestSourceLanguage(unittest.TestCase):
    def test_no_turkish_characters_in_the_package(self):
        offenders = []
        for path in sorted(PACKAGE.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if TURKISH_CHARACTERS & set(line):
                    offenders.append(f"{path.relative_to(REPOSITORY)}:{number}")

        self.assertEqual(offenders, [], f"Turkish characters remain in {offenders[:8]}")

    def test_no_turkish_words_in_the_package(self):
        offenders = []
        for path in sorted(PACKAGE.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                words = set(re.findall(r"[a-zçğıöşü]+", line.lower()))
                if words & TURKISH_WORDS:
                    offenders.append(f"{path.relative_to(REPOSITORY)}:{number}")

        self.assertEqual(offenders, [], f"Turkish words remain in {offenders[:8]}")


class TestDocumentsExist(unittest.TestCase):
    def test_each_expected_document_is_present(self):
        for name, path in DOCUMENTS.items():
            with self.subTest(document=name):
                self.assertTrue(path.is_file(), f"{path} is missing")

    def test_readme_links_to_each_of_them(self):
        readme = DOCUMENTS["README.md"].read_text(encoding="utf-8")

        for target in ("CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "ARCHITECTURE.md"):
            with self.subTest(target=target):
                self.assertIn(target, readme)


class TestLinkIntegrity(unittest.TestCase):
    def test_every_relative_markdown_link_resolves(self):
        pattern = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
        broken = []

        for path in _markdown_files():
            for target in pattern.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                resolved = (path.parent / target.split("#")[0]).resolve()
                if not resolved.exists():
                    broken.append(f"{path.relative_to(REPOSITORY)} -> {target}")

        self.assertEqual(broken, [], f"broken links: {broken}")


class TestDecisionRecords(unittest.TestCase):
    def _records(self):
        return sorted((REPOSITORY / "docs" / "adr").glob("[0-9]*.md"))

    def test_there_is_at_least_one_record(self):
        self.assertTrue(self._records())

    def test_each_record_has_the_standard_sections(self):
        for path in self._records():
            text = path.read_text(encoding="utf-8")
            for section in ("## Context", "## Decision", "## Consequences"):
                with self.subTest(record=path.name, section=section):
                    self.assertIn(section, text)

    def test_each_record_states_its_status(self):
        for path in self._records():
            with self.subTest(record=path.name):
                self.assertIn("Status", path.read_text(encoding="utf-8"))

    def test_the_index_lists_every_record(self):
        index = (REPOSITORY / "docs" / "adr" / "README.md").read_text(encoding="utf-8")

        for path in self._records():
            with self.subTest(record=path.name):
                self.assertIn(path.name, index)


class TestChangelog(unittest.TestCase):
    def test_it_records_the_breaking_changes(self):
        changelog = DOCUMENTS["CHANGELOG.md"].read_text(encoding="utf-8")

        # The four changes that break an existing installation.
        for item in ("MIT", "code_reviewer", "ai-code-review", "2.0.0"):
            with self.subTest(item=item):
                self.assertIn(item, changelog)


if __name__ == "__main__":
    unittest.main()
