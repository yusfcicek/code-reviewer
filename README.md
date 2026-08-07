# Enterprise AI Code Review Agent
**Codebase-Aware Impact Architect**

An AI code review agent for CI/CD pipelines. It triages a merge request before
spending tokens on it, runs static analyzers over the changed files, asks an LLM
for an architectural review, and turns the result into a pipeline decision.

> **Status: alpha, under active repair.** This repository was imported as a
> working prototype and is being brought up to production quality in staged
> levels. Capabilities that are still incomplete are listed explicitly under
> [Current status](#-current-status) rather than hidden. See
> [`docs/roadmap/`](docs/roadmap/README.md) for the full inventory and plan.

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

### 🔒 4. Confinement
Every file the agent reads is resolved against the checkout under review and
refused if it lands outside — including through `..` and symlinks. The paths the
agent asks for ultimately come from the diff, so anyone who can open a merge
request could otherwise attempt to steer them.

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
| Agent tool loop | ✅ Works | Tool catalogue and scratchpad both use the Hermes dialect the parser reads; exercised end to end against a scripted model |
| Token-aware memory | ✅ Works | The prompt template declares the memory context, so collected insights reach the model |
| Policy file | ✅ Works | The bundled `review_policy.yaml` is the default, and its thresholds change what the analyzers report |
| Analyzer results feeding the gate | ✅ Works | Every reviewed file is analysed unconditionally; the gate blocks on findings and demotes prose to warnings |
| Tool sandboxing | ✅ Works | Every file tool resolves against a workspace root and refuses paths outside it, including traversal and symlinks |
| Metrics | ✅ Works | The whole review is aggregated and exported as valid OpenMetrics; every field is derived from something the review produced |
| Logging | ✅ Works | Structured `logging` with `LOG_LEVEL` and an optional JSON format |
| Resilience | ✅ Works | A failing file is reported as unreviewed; model calls carry a timeout and a retry budget |
| TLS | ✅ Safe | Certificate verification is on unless `GITLAB_SSL_VERIFY=false` is set explicitly, which warns; `GITLAB_CA_BUNDLE` is supported |

Remaining items are scheduled in [Levels 3 and 4](docs/roadmap/README.md) of
the roadmap.

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

No pipeline definition ships with the repository yet (finding F-44); the job
below is the intended shape.

```yaml
ai-code-review:
  stage: review
  image: python:3.12-slim
  script:
    - curl -LsSf https://astral.sh/uv/install.sh | sh
    - uv sync
    - uv run ai-code-review --project-id $CI_PROJECT_ID --mr-iid $CI_MERGE_REQUEST_IID
  artifacts:
    reports:
      metrics: metrics.txt
  allow_failure: true
```

---

## 🧪 Testing

```bash
uv run pytest
uv run pytest --cov          # with coverage
```

412 tests. The domain and application layers sit at 88–100 % coverage; the
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
│   │   ├── llm/                 vLLM provider, review agent, token counting
│   │   ├── memory/              SmartMemoryStrategy
│   │   ├── metrics/             Prometheus / GitLab exporter
│   │   └── tools/               tool definitions + workspace confinement
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

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📜 License

[MIT License](LICENSE)
