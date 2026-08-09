# Architecture Decision Records

One file per decision that still binds. Each states its context, the decision
and its consequences, and links to the roadmap level that made it.

A record is written *after* the decision is implemented. An ADR for a decision
nobody has taken turns this directory into a wish list.

| # | Decision | Status |
|---|---|---|
| [0001](0001-mit-licence.md) | MIT licence | Accepted |
| [0002](0002-layered-architecture.md) | Layered architecture with a one-way dependency rule | Accepted |
| [0003](0003-package-name.md) | The import package is named `code_reviewer` | Accepted |
| [0004](0004-findings-drive-the-gate.md) | The gate decides from findings; prose warns | Accepted |
| [0005](0005-workspace-confinement.md) | Agent file access is confined to the workspace | Accepted |
| [0006](0006-a-failing-file-is-reported-not-fatal.md) | A file the reviewer cannot process is reported, not fatal | Accepted |
| [0007](0007-langchain-pinned.md) | LangChain is held at 0.1.x | Superseded by 0009 |
| [0008](0008-english-source.md) | English is the language of the source | Accepted |
| [0009](0009-agent-loop-in-tree.md) | The agent's tool loop lives in this repository | Accepted |
| [0010](0010-untrusted-input-defences.md) | Untrusted input is defended in four layers, and a refusal is a finding | Accepted |
| [0011](0011-unknown-means-blocked.md) | "Unknown" is not "pass" | Accepted |
| [0012](0012-one-comment-per-merge-request.md) | One comment per merge request, and an exit code that says which failure | Accepted |
| [0013](0013-suppression-is-narrow-and-counted.md) | Suppression is narrow, reasoned and counted | Accepted |
| [0014](0014-evaluation-is-a-dataset-not-a-fixture.md) | Review quality is measured against a dataset | Accepted |
| [0015](0015-retrieval-is-hybrid-local-and-untrusted.md) | Retrieval is hybrid, local, and untrusted | Accepted |
| [0016](0016-memory-informs-and-never-decides.md) | Memory informs, and never decides | Accepted |
| [0017](0017-an-orchestrator-of-specialists-not-a-framework.md) | An orchestrator of specialists, not a framework | Accepted |
| [0018](0018-a-trace-of-our-own.md) | A trace of our own, not OpenTelemetry | Accepted |

## Adding one

Copy the shape of an existing record: `## Context`, `## Decision`,
`## Consequences`, plus a `Status` line. `tests/unit/test_documentation.py`
checks those sections exist and that this index lists every file.
