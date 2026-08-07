"""Pytest configuration for the repository root.

The package under test is imported from the repository root, which
``[tool.pytest.ini_options] pythonpath = ["."]`` in ``pyproject.toml`` puts on
``sys.path``. No path manipulation is needed here.

Test layout mirrors the package layout:

    tests/unit/domain/          pure rules, no doubles needed
    tests/unit/application/     the workflow, driven by in-memory fakes
    tests/unit/infrastructure/  analyzers, adapters and loaders
    tests/integration/          several components wired together, still offline

``tests/unit/test_architecture.py`` asserts the dependency direction between the
layers; it fails loudly if an import starts pointing the wrong way.
"""
