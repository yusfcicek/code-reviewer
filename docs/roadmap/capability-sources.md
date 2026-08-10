# Where levels 12–20 come from

Levels 0–11 were sourced from defects: 59 findings, each traceable to something
observably wrong. That source is now exhausted — the inventory is closed.

Levels 12–20 are sourced from three published role descriptions for agentic AI
work in a regulated bank (ING Türkiye, Istanbul):

| # | Role | Read as |
|---|---|---|
| S1 | AI Engineer | What the *runtime* must do: orchestration, memory, tracing, async, Kubernetes |
| S2 | Senior NLP / LLM / LLMOps Data Scientist | What the *lifecycle* must do: evaluation, monitoring, continuous optimisation, explainability |
| S3 | Senior AI/LLM Data Scientist, Agentic AI | What the *agents* must do: tools, multi-agent workflows, RAG, governance frameworks |

A role description is not a requirements document, and it is not treated as
one. Each line below is a capability the sources name, followed by what this
repository does about it today. A capability with no gap produces no level.

## Capability inventory

| ID | Capability | Sources | State before Level 12 | Level |
|---|---|---|---|---|
| C-01 | Agent evaluation and reliability frameworks | S3 | None. Nothing measures whether a review is *good* | 12 |
| C-02 | LLM application evaluation, monitoring, continuous optimisation | S2 | Runtime metrics only: counts, durations, token use — no quality signal | 12 (analyzers), 21 (the model's prose) |
| C-03 | Regression detection across model or prompt change | S2 | None. A prompt edit ships unmeasured | 12 (analyzers), 21 (the model's prose) |
| C-04 | RAG pipelines and vector-based retrieval | S1, S2, S3 | None. The agent sees one diff and one file | 13 |
| C-05 | Vector databases, embeddings, semantic search | S1, S3 | None | 13 |
| C-06 | Hybrid retrieval and re-ranking | S2 (IR) | None | 13 |
| C-07 | Short-term memory for agents | S1 | `SmartMemoryStrategy` — token-budgeted, per-run | — (met) |
| C-08 | Long-term memory mechanisms | S1 | None. Every review starts from zero | 14 |
| C-09 | Multi-agent orchestration; orchestrator and sub-agent topologies | S1, S3 | One agent, one loop | 15 |
| C-10 | Agent handoff protocols | S1 | None | 15 |
| C-11 | Tool-calling loops | S1, S3 | `ReviewAgent` — in-tree loop, Hermes dialect (Level 7) | — (met) |
| C-12 | Observable and traceable agent workflows | S1 | Structured logs and OpenMetrics; no causal trace | 16 |
| C-13 | Asynchronous programming models | S1 | Fully synchronous | 17 |
| C-14 | Microservices, REST/gRPC APIs | S1 | A CLI. No callable surface | 18 |
| C-15 | Integration with APIs, databases, enterprise platforms | S3 | GitLab only, through one port | 18 |
| C-16 | Docker, Kubernetes/OpenShift, CI/CD deployment | S1 | GitLab CI template; no image, no manifests | 19 |
| C-17 | Reliability, maintainability, scalability of deployed solutions | S1 | Partly: exit codes, fail-closed, one comment per MR (Levels 9–10) | 19 |
| C-18 | Explainability and regulatory compliance | S2 | None recorded. A finding cites a rule, not its provenance | 20 |
| C-19 | Agent governance frameworks | S3 | Suppression is audited (Level 11); model decisions are not | 20 |
| C-20 | Model/prompt versioning and cost accounting | S2 | Token counting exists; nothing pins a version to an output | 20 |
| C-21 | Grounded generation: an assistant's output checked against its input | S2, S3 | Level 12 graded the analyzers and said in its own non-goals that it did not grade the prose | 21 |
| C-22 | An agent that acts, not only reports | S1, S3 | Level 13 left it deliberately: the agent reviews, it does not write the patch | 22 |
| C-23 | Documentation checked against the code it describes | — | None. The roadmap has required it since Level 0 and nothing enforced it; three defects of this kind reached `development` | 23 |

**C-23 has no role description behind it, and the table says so.** Its source
is this project's own Level 0 working agreement — *documentation may never claim
behaviour the code does not have* — and the three documentation-overstates-code
defects the self-review of levels 12–20 found. Recording a source that does not
exist would be the exact defect the capability describes.

## What is deliberately out of scope

**Model training and fine-tuning** (S1, S2 both mention neural-network and
training familiarity). This is a review agent, not a training pipeline.
Evaluation of a hosted model is in scope at Level 12; producing one is not.

**A specific cloud's managed services** — Vertex AI, Cloud Run, Pub/Sub,
BigQuery are named by S1. Binding to one vendor's SDK would undo the ports and
adapters the first eleven levels bought. Levels 13, 18 and 19 declare ports and
ship a default adapter that runs with no cloud account; a Vertex or Azure
adapter is then a sibling module, which is the point.

**A named agent framework** — LangGraph, CrewAI, AutoGen, Semantic Kernel.
Level 7 removed a framework from the critical path because its removal of
`AgentExecutor` had already pinned this project to a January 2024 dependency
tree. Level 15 builds the orchestration this repository needs against its own
ports. If a framework is later wanted, it becomes an adapter behind them.
