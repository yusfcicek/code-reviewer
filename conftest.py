"""Pytest configuration for the repository root.

The package under test is imported from the repository root, which
``[tool.pytest.ini_options] pythonpath = ["."]`` in ``pyproject.toml`` puts on
``sys.path``. No path manipulation is needed here.

Known hazard (finding F-37): ``tests/unit/test_agent_core.py`` replaces several
``langchain`` modules in ``sys.modules`` at import time so that
``code_reviewer.infrastructure.llm.review_agent`` can be imported without the real framework.
Because ``sys.modules`` is process-global, those stubs stay in place for every
test collected afterwards, which makes results depend on collection order.

This is a defect, not a design. It is scheduled for Level 1, where the agent's
construction is inverted so the framework can be injected instead of stubbed.
Until then, do not add tests that rely on the real ``langchain`` package being
importable in the same process.
"""
