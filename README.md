# Enterprise AI Code Review Agent
**Codebase-Aware Impact Architect**

An AI code review agent for CI/CD pipelines. It triages a merge request before
spending tokens on it, runs static analyzers over the changed files, asks an LLM
for an architectural review, and turns the result into a pipeline decision.

> **Status: alpha, under active repair.** This repository was imported as a
> working prototype and is being brought up to production quality in staged
> levels. Several advertised capabilities are implemented but not correctly
> wired together — they are listed explicitly under
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
  secret patterns, quality thresholds and pipeline behaviour.
- The **review gate** turns a review report into `PASS`, `WARN` or `FAIL`.

### 📈 4. Metrics
Review duration and quality score are exported in Prometheus text format for
GitLab's `metrics` report artifact.

### 🧠 5. Token-aware memory
`SmartMemoryStrategy` keeps findings in priority buckets, never summarises
`SECURITY` or `BREAKING` insights, and compresses lower-priority context first.

---

## 📋 Current status

Honest accounting of the gap between the list above and the code, with the
finding IDs from [`docs/roadmap/findings.md`](docs/roadmap/findings.md).

| Capability | State | Detail |
|---|---|---|
| Smart triage | ✅ Works | Over-escalates: security patterns are matched against the whole diff including unchanged context (F-09) |
| Semantic / SAST / quality / performance analyzers | ✅ Work when called directly | Exposed as agent tools; a handful of individual rules misfire (F-05, F-06, F-07) |
| Dependency impact tracking | ✅ Works | Run automatically for every reviewed file |
| Policy file | ⚠️ Partial | The bundled `review_policy.yaml` is **not** loaded unless you pass `--policy` (F-04); quality and performance thresholds in it are ignored by the analyzers (F-31) |
| Review gate | ❌ Broken | The blocking path compares an enum against a string and is never taken, so the pipeline is never failed (F-01) |
| Metrics | ⚠️ Partial | Only the last analysed file is exported; security, performance and issue-count fields are always `0` (F-16, F-17) |
| Token-aware memory | ⚠️ Partial | Insights are collected and prioritised, but the context is not present in the prompt template, so the model never sees it (F-02) |
| Agent tool loop | ❌ Broken | Tools are not bound to the model, and the scratchpad format does not match the output parser (F-03) |
| TLS | ❌ Unsafe | The GitLab client is constructed with `ssl_verify=False` (F-20) |

Fixes are scheduled in [Level 1](docs/roadmap/README.md) of the roadmap.

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
`openhands/agent/config/review_policy.yaml`.

> **It is not loaded automatically.** Pass it explicitly with `--policy`, or the
> agent falls back to the narrower defaults defined in
> `openhands/agent/config/config_loader.py` (finding F-04).

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

gate:
  quality_score_threshold: 60
  fail_pipeline_on_critical: true
```

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
| `--policy` | none | Path to a policy YAML file |

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

Current coverage is thin — 10 tests over 2 of 13 modules (finding F-35).
Expanding it is part of the roadmap, and every behaviour change from Level 1
onwards is written test-first.

---

## 📂 Project structure

```
.
├── openhands/
│   └── agent/
│       ├── analyzers/       # semantic, dependency, SAST, quality, performance
│       ├── config/          # policy dataclasses, YAML loader, review_policy.yaml
│       ├── core/            # ReviewAgent and its abstract ports
│       ├── gate/            # PASS / WARN / FAIL decision
│       ├── memory/          # SmartMemoryStrategy
│       ├── metrics/         # Prometheus / GitLab metrics collector
│       ├── provider/        # vLLM (OpenAI-compatible) LLM factory
│       ├── tools/           # LangChain tool definitions
│       ├── triage/          # review triage rules
│       └── main.py          # CLI entry point and orchestration
├── tests/unit/              # unit tests
├── docs/roadmap/            # findings inventory, per-level specs and plans
└── assets/
```

This layout is technical rather than domain-oriented and is scheduled to be
restructured into domain / application / infrastructure layers in Level 2.

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📜 License

[MIT License](LICENSE)
