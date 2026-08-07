# 3. The import package is named `code_reviewer`

- **Status**: Accepted
- **Level**: [2](../roadmap/level-2/spec.md)

## Context

The import package was `openhands`, which is the namespace of the unrelated
All-Hands-AI/OpenHands project. Installing both into one environment shadows
one of them, and the resulting `ImportError` names a module that exists.

## Decision

The import package is `code_reviewer`, matching the repository name. The
distribution keeps its name, `enterprise-ai-code-reviewer`.

## Consequences

- **Breaking.** Every `from openhands.agent...` import changed. Anyone
  depending on the old path must update.
- The console entry point moved from `openhands.agent.main:main` to
  `code_reviewer.__main__:main`; the command, `ai-code-review`, is unchanged.
- The architecture test greps the repository for the old name and fails if it
  reappears.
