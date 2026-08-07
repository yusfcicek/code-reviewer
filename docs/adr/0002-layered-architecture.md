# 2. Layered architecture with a one-way dependency rule

- **Status**: Accepted
- **Level**: [2](../roadmap/level-2/spec.md)

## Context

The tree was arranged by technical role — `analyzers/`, `tools/`, `provider/`,
`gate/` — with no boundary between the rules of code review and the machinery
that talks to GitLab, vLLM, `grep` and the filesystem.

The cost was concrete rather than aesthetic. The orchestration reached into
`project.mergerequests.get(...)` directly, so exercising the workflow required a
live GitLab. The one place where triage, the agent, the gate and metrics met was
the one place with no tests.

## Decision

Three layers, with dependencies pointing one way:

```
infrastructure  ──►  application  ──►  domain
```

- `domain/` holds the rules. Standard library only.
- `application/` holds the workflow and declares the ports it needs.
- `infrastructure/` implements those ports.

`tests/unit/test_architecture.py` parses every module's imports and fails if the
direction reverses.

## Consequences

- The workflow has 33 tests that run offline against in-memory fakes.
- Adding a forge is a sibling module; nothing above infrastructure changes.
- The application layer uses the standard `logging` module rather than the
  infrastructure helper, because importing downwards is exactly what the rule
  forbids. The architecture test caught that during Level 4.
- A contributor cannot take the convenient shortcut without a red build.
