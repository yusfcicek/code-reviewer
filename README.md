# Enterprise AI Code Review Agent
**Codebase-Aware Impact Architect**

An AI code review agent for CI/CD pipelines. It triages a merge request before
spending tokens on it, runs static analyzers over the changed files, asks an LLM
for an architectural review, and turns the result into a pipeline decision.

> **Status: 2.2.0.** Rebuilt from an imported prototype across nine levels of
> work. 59 defects were found and recorded and all 59 are now fixed — the last
> deferred one closed in Level 7. 584 tests at 88 % coverage; lint, formatting,
> types, tests and a dependency audit with an empty ignore list all gate on CI.
> Levels 7-8 closed a further nine gaps found by comparing against a sibling
> implementation.
> What each level did, and what it found, is in
> [`docs/roadmap/`](docs/roadmap/README.md).

---

## 🚀 Capabilities

### 🧠 1. Smart Review Triage
Classifies each changed file before any LLM call:
- **SKIP** — file types excluded by policy (docs, lock files).
- **AUTO_APPROVE** — comment-only, whitespace-only, or minimal non-logic changes.
- **CRITICAL** — security-sensitive patterns or public API removals.
- **QUICK_SCAN / FULL_REVIEW** — chosen by the size of the change.

### 🔍 2. Static analyzers
- **Semantic change analysis** — AST-based classification into `REFACTOR`,
  `FEATURE`, `BUGFIX`, `BREAKING_CHANGE`, with a risk score.
- **Dependency impact tracking** — forward imports and reverse references, plus
  a two-level ripple-effect trace, so code outside the diff is considered.
- **SAST** — SQL injection, XSS, command injection, path traversal, hardcoded
  secrets, weak crypto and insecure deserialisation, mapped to CWE and OWASP
  Top 10.
- **Code quality** — SOLID violations, cyclomatic complexity, duplicate blocks,
  testability and error-handling analysis.
- **Performance** — nested-loop complexity, recursion, N+1 query patterns and
  unclosed resources.

### 🛡️ 3. Policy and gate
- Rules are declared in `review_policy.yaml` — skip patterns, banned patterns,
  secret patterns, quality thresholds and pipeline behaviour. Thresholds are
  enforced: raising `max_class_methods` changes what is reported.
- Every reviewed file is analysed **unconditionally**, not only when the model
  asks for it, and the findings drive the decision.
- The **review gate** turns findings and the review report into `PASS`, `WARN`
  or `FAIL`. Findings block; the model's prose warns. Each reason names its
  source, so an analyzer's verdict is distinguishable from the model's opinion.
- `gate.blocking_severity` sets how severe a finding has to be to fail a
  pipeline. It defaults to `critical`.

### 🔒 4. Defences against the content under review
The diff is written by whoever opened the merge request, so it is treated as
hostile input in five places
([ADR 0010](docs/adr/0010-untrusted-input-defences.md)):

- **A declared trust boundary.** The diff and the file content are wrapped in
  `<untrusted_diff>` / `<untrusted_file_content>`, both tag forms escaped
  inside the content, and the system prompt opens by declaring everything
  inside them to be data rather than instructions.
- **Confinement.** Every path is resolved against the checkout and refused if
  it lands outside, including through `..` and symlinks.
- **A deny-list and a read budget.** `.env`, `id_rsa`, `*.pem`, `*.key` and
  anything under `.git/` are refused at any depth, and listings omit them
  rather than naming them. A per-review total read budget means an
  exfiltration cannot proceed one ordinary file at a time.
- **Fixed-string search.** `grep` runs with `-F` after `--`, bounded, with
  credential files excluded, so a model-supplied pattern is data rather than a
  program.
- **Redaction.** The review text is masked on the way out — the values of the
  secrets this process holds first, then known secret shapes.

**A refused access becomes a `CRITICAL` finding**, so an injection attempt can
fail the pipeline rather than merely be mentioned in the report.

### 📈 5. Metrics and logging
- The whole review is exported as OpenMetrics text for GitLab's `metrics`
  report: files and lines analysed, findings per severity, triage decisions,
  gate result, total and slowest duration — each with `# HELP` and `# TYPE`.
- Diagnostics go through `logging`. `LOG_LEVEL` sets verbosity and
  `LOG_FORMAT=json` emits one JSON object per record for an aggregator.
- A file the reviewer cannot process is reported as *not reviewed* rather than
  ending the run or passing silently.

### 🧠 6. Token-aware memory
`SmartMemoryStrategy` keeps findings in priority buckets, never summarises
`SECURITY` or `BREAKING` insights, and compresses lower-priority context first.

---

## 📋 Current status

Honest accounting of the gap between the list above and the code, with the
finding IDs from [`docs/roadmap/findings.md`](docs/roadmap/findings.md).

| Capability | State | Detail |
|---|---|---|
| Smart triage | ✅ Works | Security patterns are matched against added lines only, so unchanged context no longer escalates a file |
| Semantic / SAST / quality / performance analyzers | ✅ Work | Exposed as agent tools and covered by tests at 83–93 % |
| Dependency impact tracking | ✅ Works | Run automatically for every reviewed file |
| Review gate | ✅ Works | A failing gate blocks the run and exits non-zero when the policy asks for it |
| Agent tool loop | ✅ Works | Both protocols — native `tool_calls` and Hermes XML — reach the tools, with every argument; the loop is in-tree and exercised end to end in each dialect |
| Token-aware memory | ✅ Works | The prompt template declares the memory context, so collected insights reach the model |
| Policy file | ✅ Works | The bundled `review_policy.yaml` is the default, and its thresholds change what the analyzers report |
| Analyzer results feeding the gate | ✅ Works | Every reviewed file is analysed unconditionally; the gate blocks on findings and demotes prose to warnings |
| Tool sandboxing | ✅ Works | Confinement, a credential deny-list, a per-review read budget and an audit log; a refusal becomes a CRITICAL finding |
| Prompt-injection containment | ✅ Works | Reviewed content is delimited and declared untrusted, and cannot close its own delimiter |
| Secret redaction | ✅ Works | Environment secret values and known secret shapes are masked before the review is published |
| Metrics | ✅ Works | The whole review is aggregated and exported as valid OpenMetrics; every field is derived from something the review produced |
| Logging | ✅ Works | Structured `logging` with `LOG_LEVEL` and an optional JSON format |
| Resilience | ✅ Works | A failing file is reported as unreviewed; model calls carry a timeout and a retry budget |
| TLS | ✅ Safe | Certificate verification is on unless `GITLAB_SSL_VERIFY=false` is set explicitly, which warns; `GITLAB_CA_BUNDLE` is supported |
| Dependencies | ✅ Current | LangChain 1.x; `pip-audit` runs in CI and reports no advisory, with an empty ignore list |

Work still queued against the variant gap analysis is scheduled in
[Levels 9-11](docs/roadmap/README.md).

---

## 📸 Example output

Example of the report the agent posts on a GitLab merge request:

![AI Review Report Example](assets/ai-review-report.jpg)

---

## 🛠️ Installation

### Prerequisites
- Python 3.12+
- A GitLab instance (cloud or self-hosted)
- vLLM or any OpenAI-compatible chat completions endpoint

### Setup

```bash
git clone https://github.com/yusfcicek/code-reviewer.git
cd code-reviewer

# install uv if you do not have it: https://github.com/astral-sh/uv
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync
```

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `GITLAB_URL` | yes | Base URL of the GitLab instance |
| `GITLAB_TOKEN` | yes | Personal or project access token with API scope |
| `VLLM_API_URL` | yes | OpenAI-compatible base URL, e.g. `http://host:8000/v1` |
| `VLLM_API_KEY` | yes | API key for that endpoint |
| `VLLM_MODEL` | yes | Model name to request |
| `CI_PROJECT_ID` | no | Fallback for `--project-id` |
| `CI_MERGE_REQUEST_IID` | no | Fallback for `--mr-iid` |
| `GITLAB_CA_BUNDLE` | no | CA certificate bundle for an internal GitLab |
| `GITLAB_SSL_VERIFY` | no | Set to `false` to disable certificate verification (not recommended) |
| `LOG_LEVEL` | no | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |
| `LOG_FORMAT` | no | `text` (default) or `json` |
| `LLM_TIMEOUT_SECONDS` | no | Request timeout for the model, default `120` |
| `LLM_MAX_RETRIES` | no | Retries on timeout or 5xx, default `2` |
| `LLM_TEMPERATURE` | no | Sampling temperature, default `0.3` |
| `REVIEW_TOOL_PROTOCOL` | no | How tools are offered: `auto` (default), `native`, `hermes`, `none` |
| `REVIEW_MAX_ITERATIONS` | no | Tool rounds allowed per file, default `10` |
| `REVIEW_MAX_SECONDS` | no | Wall-clock budget for one file. Unset means none — see below |
| `WORKSPACE_MAX_FILE_BYTES` | no | Per-file truncation threshold, default `200000` |
| `WORKSPACE_TOTAL_READ_BUDGET` | no | Bytes one review may read in total, default `20000000` |

```bash
export GITLAB_URL="https://gitlab.example.com"
export GITLAB_TOKEN="your-access-token"
export VLLM_API_URL="http://vllm-endpoint:8000/v1"
export VLLM_API_KEY="your-api-key"
export VLLM_MODEL="mistralai/Mistral-7B-Instruct-v0.2"
```

---

## ⚙️ Configuration

Behaviour is driven by a policy file. A reference policy ships at
`code_reviewer/infrastructure/config/review_policy.yaml`.

It is loaded automatically. Resolution order, highest priority first:

1. the path given to `--policy`
2. `review_policy.yaml`, `.review_policy.yaml`, `.agent/review_policy.yaml` or
   `config/review_policy.yaml` in the working directory
3. the file bundled with the package
4. the dataclass defaults in `code_reviewer/infrastructure/config/loader.py`

The chosen source is printed at startup, because "which policy actually
applied" is the first question when a review surprises someone.

```yaml
triage:
  skip_patterns:
    - ".*\\.md$"
    - ".*\\.lock$"
  allow_only_comments: true

security:
  block_on_critical: true
  banned_patterns:
    - "eval\\s*\\("
    - "exec\\s*\\("

quality:
  max_class_methods: 15
  max_cyclomatic_complexity: 15

gate:
  blocking_severity: "critical"   # critical | high | medium | low | info
  quality_score_threshold: 60
  fail_pipeline_on_critical: true
  fail_on_review_error: false     # a file the reviewer could not process
```

Documentation, generated lock files, binary assets and vendored trees are
skipped by default. Dockerfiles, pipeline definitions, Kubernetes manifests,
Terraform and dependency manifests are **not** — that is where a privilege
escalation or a changed base image hides.

Selected values can be overridden from the environment with `REVIEW_POLICY_*`
variables — see `ReviewPolicyLoader._load_from_env` for the supported keys.

---

## 🏃 Usage

```bash
uv run ai-code-review --project-id <PROJECT_ID> --mr-iid <MR_IID>
```

**Options**

| Flag | Default | Meaning |
|---|---|---|
| `--project-id` | `$CI_PROJECT_ID` | GitLab project ID |
| `--mr-iid` | `$CI_MERGE_REQUEST_IID` | Merge request IID |
| `--policy` | bundled `review_policy.yaml` | Path to a policy YAML file |

### GitLab CI

The repository ships `.gitlab-ci.yml`; this is the review job from it.

```yaml
ai-code-review:
  stage: review
  image: python:3.12-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  before_script:
    - pip install --quiet uv
    - uv sync --frozen
  script:
    - uv run ai-code-review --project-id "$CI_PROJECT_ID" --mr-iid "$CI_MERGE_REQUEST_IID"
  artifacts:
    when: always
    reports:
      metrics: metrics.txt
  allow_failure: true
```

`allow_failure: true` keeps a review that cannot run from blocking a merge.
Set it to `false` once you trust the verdict, and use
`gate.fail_pipeline_on_critical` and `gate.blocking_severity` to decide what
"trust" means.

### Tool calling

The agent runs against two kinds of endpoint, and they carry a tool call
differently:

| Endpoint | How a tool call arrives |
|---|---|
| On-prem vLLM with a Hermes template | XML in the message text: `<tool_call><function=…>` |
| OpenAI, Groq, most hosted APIs | a structured `tool_calls` field on the message |

The parser reads both, and `REVIEW_TOOL_PROTOCOL` decides how tools are
offered:

- `auto` (default) — bind natively; if the server refuses, fall back to the
  prompt catalogue and Hermes calls. Works on either kind of endpoint.
- `native` — require native binding, and fail loudly if it is unsupported.
- `hermes` — never bind. For a vLLM started without
  `--enable-auto-tool-choice`, where the model emits XML instead.
- `none` — no tools; the model narrates from the diff alone.

The loop that drives them is `infrastructure/llm/narration_loop.py` rather than
LangChain's: 1.0 removed `AgentExecutor`, and its replacement offers no
output-parser hook, so it cannot support the Hermes path at all
([ADR 0009](docs/adr/0009-agent-loop-in-tree.md)).

**Cost.** With tools bound the model actually reads files and runs scans, so a
review takes materially longer than one without. The verdict never depends on
this — it comes from static analysis either way — so `none` is a legitimate
choice when only the gate is wanted.

**There is no wall-clock limit by default.** `REVIEW_MAX_SECONDS` is unset,
because cutting an analysis off part-way produces an incomplete report that
does not say it is incomplete, and that error points towards approval. The loop
is still bounded: `REVIEW_MAX_ITERATIONS` (default 10) caps the tool rounds and
the provider applies a per-request timeout (default 120 s), so the worst case is
finite. Set `REVIEW_MAX_SECONDS` to a positive number if your CI needs a hard
ceiling; `0` or unset means no limit.

---

## 🧪 Development

```bash
uv sync
uv run pre-commit install

uv run ruff check code_reviewer tests          # lint
uv run ruff format code_reviewer tests         # format
uv run mypy                                    # types (domain + application)
uv run pytest                                  # tests
uv run pytest --cov                            # tests with the coverage floor
./scripts/audit-deps.sh                        # dependency advisories
```

CI runs exactly these five checks — `.github/workflows/ci.yml` on GitHub and
`.gitlab-ci.yml` on GitLab. The GitLab pipeline also runs this agent against
its own merge requests, so the job below is one the project uses on itself.

584 tests, 88 % coverage with an enforced floor of 87 %. The dependency
audit runs with an empty ignore list. The domain and
application layers sit at 88–100 %; the
review workflow runs entirely against in-memory fakes, with no network and no
GitLab. Every behaviour change from Level 1 onwards is written test-first: the
test that pins a fix is observed failing before the fix lands.

---

## 📂 Project structure

```
.
├── code_reviewer/
│   ├── domain/                  rules of code review — no I/O, no frameworks
│   │   ├── severity.py          the one ordered Severity
│   │   ├── finding.py           Finding, FindingCategory, AffectedCode
│   │   ├── policy.py            ReviewPolicy and its sections
│   │   ├── triage.py            triage decisions
│   │   ├── gate.py              per-file PASS / WARN / FAIL
│   │   └── outcome.py           merge-request-level verdict
│   ├── application/             the workflow and the ports it needs
│   │   ├── ports.py             CodeForge, LLMProvider, MemoryStrategy, Reviewer
│   │   ├── review_service.py    the use case
│   │   └── report.py            merge-request comment rendering
│   ├── infrastructure/          adapters onto the outside world
│   │   ├── analyzers/           semantic, dependency, SAST, quality, performance, suite
│   │   ├── config/              YAML loader + review_policy.yaml
│   │   ├── forge/               GitLab client and CodeForge adapter
│   │   ├── llm/                 vLLM provider, review agent, tool loop, token counting
│   │   ├── memory/              SmartMemoryStrategy
│   │   ├── metrics/             Prometheus / GitLab exporter
│   │   ├── security/            secret redaction on the way out
│   │   └── tools/               tool definitions, workspace limits, safe search
│   ├── cli.py                   argument parsing
│   └── __main__.py              composition root
├── tests/
│   ├── unit/{domain,application,infrastructure}/
│   └── integration/
├── docs/roadmap/                findings inventory, per-level specs and plans
└── assets/
```

Dependencies point one way: `infrastructure → application → domain`. The domain
imports nothing but the standard library, so its rules are testable without a
single mock. `tests/unit/test_architecture.py` parses every module's imports and
fails if that direction is ever reversed.

---

## 📚 Documentation

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | The layers, the ports, the path of one review, and how to extend it |
| [docs/adr/](docs/adr/README.md) | Eight decision records: what was decided, why, and what it costs |
| [docs/roadmap/](docs/roadmap/README.md) | The 59-item findings inventory and the seven levels of work it produced |
| [SECURITY.md](SECURITY.md) | The threat model, prompt injection through a diff, and hardening advice |
| [CHANGELOG.md](CHANGELOG.md) | What changed, including every breaking change |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branching, commits, the TDD expectation, the design rules |

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📜 License

[MIT License](LICENSE)
