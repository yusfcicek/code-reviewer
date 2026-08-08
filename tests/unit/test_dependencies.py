"""The dependency surface is part of the product.

An agent whose job is to report other people's vulnerable dependencies has to
keep its own surface small and current. Two properties are cheap to state and
cheap to check, and both were violated before Level 7:

- A declared dependency that nothing imports is attack surface acquired for
  nothing. ``langchain-community`` sat in the manifest to satisfy exactly one
  test import and brought ``aiohttp``, ``SQLAlchemy`` and ``dataclasses-json``
  with it (finding G-01).
- A dependency the source reaches for but does not declare works on the machine
  that has it and fails everywhere else.

These are structural facts about the tree, so they are checked by reading it
rather than by installing anything.
"""

import ast
import sys
import tomllib
import unittest
from pathlib import Path
from typing import ClassVar

REPOSITORY = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY / "code_reviewer"
TESTS = REPOSITORY / "tests"

#: Distributions that must not reappear, with the reason each one left.
BANNED_DISTRIBUTIONS = {
    "langchain-community": (
        "imported nowhere; pulls aiohttp, SQLAlchemy and dataclasses-json into the tree for nothing (G-01)"
    ),
}

#: Import names corresponding to the banned distributions.
BANNED_IMPORTS = {"langchain_community"}


def _python_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py")) + sorted(TESTS.rglob("*.py"))


def _top_level_imports(path: Path) -> set[str]:
    """Every top-level module name imported by ``path``, however deeply nested.

    ``ast.walk`` rather than a regex: an import inside a function or a
    ``try`` block is still an import, and the codebase has several of both.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # `node.module` is None for a relative import, which is first-party.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


class TestBannedDependencies(unittest.TestCase):
    def setUp(self):
        self.manifest = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())

    def test_no_banned_distribution_is_declared(self):
        declared = "\n".join(self.manifest["project"]["dependencies"])

        for distribution, reason in BANNED_DISTRIBUTIONS.items():
            with self.subTest(distribution=distribution):
                self.assertNotIn(
                    distribution,
                    declared,
                    f"'{distribution}' is declared again: {reason}",
                )

    def test_no_module_imports_a_banned_distribution(self):
        offenders = [
            f"{path.relative_to(REPOSITORY)} imports {name}"
            for path in _python_files()
            for name in sorted(_top_level_imports(path) & BANNED_IMPORTS)
        ]

        self.assertEqual(
            offenders,
            [],
            "Banned import(s) found:\n" + "\n".join(offenders),
        )


class TestDeclaredDependenciesCoverTheImports(unittest.TestCase):
    """Every third-party module the package imports is declared.

    Scoped to ``code_reviewer/`` on purpose: the test suite may reach for a dev
    dependency, which is declared in a different table.
    """

    #: Import name -> distribution that provides it, where they differ.
    PROVIDED_BY: ClassVar[dict[str, str]] = {
        "gitlab": "python-gitlab",
        "langchain_core": "langchain",
        "langchain_openai": "langchain-openai",
        "yaml": "PyYAML",
    }

    #: Import names that need no declaration: the standard library and the
    #: package itself. Kept explicit rather than derived, so a new third-party
    #: import cannot be waved through by a heuristic.
    FIRST_PARTY_OR_STDLIB = frozenset({"code_reviewer"})

    def test_every_third_party_import_is_declared(self):
        manifest = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())
        declared = "\n".join(manifest["project"]["dependencies"]).lower()

        undeclared = set()
        for path in sorted(PACKAGE.rglob("*.py")):
            for name in _top_level_imports(path):
                if name in sys.stdlib_module_names or name in self.FIRST_PARTY_OR_STDLIB:
                    continue
                distribution = self.PROVIDED_BY.get(name, name)
                if distribution.lower() not in declared:
                    undeclared.add(f"{name} (from {distribution})")

        self.assertEqual(
            sorted(undeclared),
            [],
            "Imported but not declared in [project.dependencies]:\n" + "\n".join(sorted(undeclared)),
        )


if __name__ == "__main__":
    unittest.main()
