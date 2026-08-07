"""Enterprise AI code review agent.

Layout follows a one-way dependency rule:

    infrastructure  →  application  →  domain

- ``domain`` holds the rules of code review — severities, findings, triage
  decisions, policy and the gate. Pure Python: no I/O, no frameworks, testable
  without mocks.
- ``application`` orchestrates a review through ports it declares itself. It
  knows what a review *is*, not where the diff comes from.
- ``infrastructure`` implements those ports against GitLab, vLLM, the
  filesystem and ``grep``.

``tests/unit/test_architecture.py`` enforces the rule.
"""

__version__ = "2.0.0"
