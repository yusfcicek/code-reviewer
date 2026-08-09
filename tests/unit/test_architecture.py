"""Enforces the layering rule that Level 2 introduced.

    infrastructure  →  application  →  domain

The rule is easy to state and easy to erode: one convenient import of `gitlab`
inside a use case, or of a YAML loader inside a domain rule, and the domain is
no longer testable without the world attached. This test parses every module's
imports and fails on the first violation, naming the module and the import.
"""

import ast
import unittest
from collections.abc import Iterator
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "code_reviewer"

#: Third-party packages that tie a module to a particular piece of machinery.
FRAMEWORKS = {
    "gitlab",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_openai",
    "openai",
    "httpx",
    "requests",
}

#: Standard-library modules that mean a module performs I/O.
IO_MODULES = {"subprocess", "socket", "urllib", "http", "shutil"}


def _modules(layer: str) -> Iterator[tuple[Path, ast.Module]]:
    """Yields every module in a layer with its parsed syntax tree."""
    directory = PACKAGE_ROOT / layer if layer else PACKAGE_ROOT
    if not directory.is_dir():
        return
    for path in sorted(directory.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_roots(tree: ast.Module) -> list[str]:
    """Top-level package name of every import in the module."""
    roots = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, stays inside the package
                continue
            if node.module:
                roots.append(node.module.split(".")[0])
    return roots


def _imported_layers(tree: ast.Module) -> list[str]:
    """Which `code_reviewer.<layer>` packages a module imports from."""
    layers = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module]
        for name in names:
            parts = name.split(".")
            if parts[0] == "code_reviewer" and len(parts) > 1:
                layers.append(parts[1])
    return layers


class TestPackageExists(unittest.TestCase):
    def test_the_package_directory_is_present(self):
        self.assertTrue(PACKAGE_ROOT.is_dir(), f"{PACKAGE_ROOT} does not exist")

    def test_each_layer_is_present(self):
        for layer in ("domain", "application", "infrastructure"):
            with self.subTest(layer=layer):
                self.assertTrue((PACKAGE_ROOT / layer).is_dir())


class TestDomainIsPure(unittest.TestCase):
    def test_domain_does_not_import_other_layers(self):
        for path, tree in _modules("domain"):
            with self.subTest(module=path.name):
                forbidden = [layer for layer in _imported_layers(tree) if layer != "domain"]
                self.assertEqual(forbidden, [], f"{path} imports {forbidden}")

    def test_domain_does_not_import_frameworks(self):
        for path, tree in _modules("domain"):
            with self.subTest(module=path.name):
                forbidden = sorted(set(_imported_roots(tree)) & FRAMEWORKS)
                self.assertEqual(forbidden, [], f"{path} imports {forbidden}")

    def test_domain_does_not_perform_io(self):
        for path, tree in _modules("domain"):
            with self.subTest(module=path.name):
                forbidden = sorted(set(_imported_roots(tree)) & IO_MODULES)
                self.assertEqual(forbidden, [], f"{path} imports {forbidden}")

    def test_domain_does_not_read_configuration_files(self):
        """Parsing YAML is a loader's job; the domain receives objects."""
        for path, tree in _modules("domain"):
            with self.subTest(module=path.name):
                self.assertNotIn("yaml", _imported_roots(tree), f"{path} imports yaml")


class TestApplicationDependsOnlyDownwards(unittest.TestCase):
    def test_application_does_not_import_infrastructure(self):
        for path, tree in _modules("application"):
            with self.subTest(module=path.name):
                self.assertNotIn("infrastructure", _imported_layers(tree), f"{path} imports infrastructure")

    def test_application_does_not_import_frameworks(self):
        for path, tree in _modules("application"):
            with self.subTest(module=path.name):
                forbidden = sorted(set(_imported_roots(tree)) & FRAMEWORKS)
                self.assertEqual(forbidden, [], f"{path} imports {forbidden}")


class TestNoLegacyPackage(unittest.TestCase):
    def test_the_old_package_name_is_gone(self):
        """`openhands` is the import namespace of an unrelated project (F-33)."""
        legacy_name = "open" + "hands"  # split so this file is not its own offender
        repository = PACKAGE_ROOT.parent
        offenders = [
            path
            for path in repository.rglob("*.py")
            if ".venv" not in path.parts
            and path != Path(__file__).resolve()
            and legacy_name in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(offenders, [], f"references to the old package remain in {offenders}")


class TestSingleSharedModels(unittest.TestCase):
    def _class_definitions(self, name: str) -> list[Path]:
        found = []
        for path, tree in _modules(""):
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == name:
                    found.append(path)
        return found

    def test_exactly_one_severity_type(self):
        self.assertEqual(len(self._class_definitions("Severity")), 1)

    def test_exactly_one_finding_type(self):
        self.assertEqual(len(self._class_definitions("Finding")), 1)

    def test_exactly_one_affected_code_type(self):
        self.assertEqual(len(self._class_definitions("AffectedCode")), 1)


if __name__ == "__main__":
    unittest.main()


class TestTheInstrumentIsNotInTheReviewPath(unittest.TestCase):
    """Level 21, AC-14 — a grader that can change a verdict is not a grader.

    The narration harness reads recorded reviews and scores them. Nothing in
    the path that produces a review may import it: the moment a check can
    influence what gets published, the number it reports is about a system
    that was watching itself being measured.
    """

    #: Modules that run when a merge request is reviewed.
    REVIEW_PATH = (
        "code_reviewer/application/review_service.py",
        "code_reviewer/application/report.py",
        "code_reviewer/application/orchestration_service.py",
        "code_reviewer/application/governance.py",
        "code_reviewer/__main__.py",
        "code_reviewer/serve.py",
        "code_reviewer/cli.py",
    )

    GRADER = ("narration", "narration_evaluation", "narration_report", "narration_dataset")

    def test_no_module_in_the_review_path_imports_the_grader(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        for relative in self.REVIEW_PATH:
            with self.subTest(module=relative):
                tree = ast.parse((root / relative).read_text(encoding="utf-8"))
                imported = {
                    name.split(".")[-1]
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module
                    for name in (node.module,)
                }
                self.assertEqual(imported & set(self.GRADER), set(), relative)

    def test_the_grader_is_reachable_from_the_evaluation_entry_point(self):
        """The other half of the rule: unreachable is not the same as
        uninvolved, and a harness nothing can run is not a harness."""
        import ast
        from pathlib import Path

        source = (Path(__file__).resolve().parents[2] / "code_reviewer/evaluate.py").read_text(
            encoding="utf-8"
        )
        modules = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        }

        assert any("narration" in module for module in modules)
