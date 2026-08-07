# 8. English is the language of the source

- **Status**: Accepted
- **Level**: [6](../roadmap/level-6/spec.md)

## Context

Ten modules carried Turkish docstrings and comments while the README,
CONTRIBUTING, the commit messages, the newer code and the review output the
agent posts were all English. A reader hit the boundary mid-file.

Several of those comments also described behaviour that Levels 1-5 changed —
the gate that could not block, the policy that was never loaded — so they were
wrong as well as inconsistent.

## Decision

The source is in English. Comments were re-derived against the code rather than
translated, because translating a wrong comment produces a fluent lie.

`tests/unit/test_documentation.py` guards the boundary.

One exception: the bug-fix markers in the semantic analyzer are patterns matched
against *other people's* code, so that list is deliberately multilingual. The
language test skips raw-string literals for exactly this reason.

## Consequences

- One language throughout, matching the project's public surface.
- The distinction between prose and pattern data is now explicit and tested.
- The roadmap and level specs stay as written; they were English already.
