# Findings Inventory

Every file in the imported baseline (commit `51a7492`) was read line by line.
This document records what was found, why it matters, and which roadmap level
owns the fix. Line references point at the **baseline** commit.

Severity legend:

- 🔴 **Critical** — the advertised behaviour does not happen at all, or the code
  is unsafe.
- 🟠 **High** — the behaviour is wrong in common cases, or the design blocks
  further work.
- 🟡 **Medium** — noisy, misleading, or a maintenance hazard.
- 🟢 **Low** — polish, consistency, ergonomics.

---

## A. Correctness — features that silently do nothing

| ID | Sev | Location | Finding |
|---|---|---|---|
| F-01 | 🔴 | `openhands/agent/main.py:146` | `gate_eval.result` is a `ReviewGateResult` enum but is compared against the string `"fail"`. The enum does not subclass `str`, so the comparison is **always false**. `overall_status` never becomes `"fail"`, the "Pipeline BLOCKED" header is unreachable, and `sys.exit(1)` at line 189 is dead code. The product's headline feature — blocking a pipeline — does not work. |
| F-02 | 🔴 | `openhands/agent/core/agent.py:189-206` | The prompt template declares only `{input}` and `agent_scratchpad`, but the runnable also feeds `memory_context`. `ChatPromptTemplate` ignores unknown keys, so **the entire smart-memory context never reaches the model**. The "Cognitive Memory Management" feature is inert from the model's point of view. |
| F-03 | 🔴 | `openhands/agent/core/agent.py:195` | `llm_with_tools = self.llm` — tools are never bound to the model. Combined with `format_to_openai_function_messages` (OpenAI function-call format) feeding a parser that reads Hermes XML, the agent's tool loop cannot work as designed. |
| F-04 | 🔴 | `openhands/agent/config/config_loader.py:113-166` | The bundled `openhands/agent/config/review_policy.yaml` is **never loaded**. `DEFAULT_POLICY_PATHS` are all relative to the current working directory. Without an explicit `--policy`, the richer YAML rule set (extra banned patterns, secret patterns, custom rules) is silently replaced by the dataclass defaults. README claims the bundled file is the default. |
| F-05 | 🟠 | `openhands/agent/analyzers/performance_analyzer.py:429` | `any('for ' in lines[a:b] or 'while ' in lines[a:b] for _ in [1])` performs a membership test against a **list**, which requires exact element equality. It is always false, so string-concatenation-in-loop detection never fires. |
| F-06 | 🟠 | `openhands/agent/analyzers/sast_analyzer.py:204` | `yaml\.load\s*\([^)]*(?!Loader\s*=)` — the negative lookahead sits after a greedy match and can always find a position where it succeeds. Effectively every `yaml.load(` matches, including safe ones. |
| F-07 | 🟠 | `openhands/agent/analyzers/sast_analyzer.py:530`, `quality_analyzer.py:684`, `performance_analyzer.py:575` | Findings are sorted by `severity.value`, i.e. **alphabetically**: `critical < high < info < low < medium`. The comment claims critical and high come first, but `info` and `low` outrank `medium`. The 15-item truncation then drops findings semi-randomly. |
| F-08 | 🟠 | `openhands/agent/analyzers/dependency_tracker.py:257` | `elif ':' in context and symbol_name in context.split(':')[1] if ':' in context else False` — operator precedence wraps the whole condition in a conditional expression. The intent is unrecoverable from the code and the branch behaves accidentally. |
| F-09 | 🟠 | `openhands/agent/triage/review_triage.py:169` | Critical-pattern matching runs over the **whole diff**, including unchanged context lines and removed lines. A file that merely mentions `password` anywhere near the hunk is escalated to `CRITICAL`, forcing an expensive review. This defeats the cost-saving purpose of triage. |
| F-10 | 🟠 | `openhands/agent/gate/review_gate.py:78-79` | When the model's markdown does not contain a `SOLID Compliance: [n/100]` line, `quality_score` defaults to `0`, which is below every threshold. Once F-01 is fixed this turns into "block every merge request whose report formatting drifted". |
| F-11 | 🟠 | `openhands/agent/memory/strategies.py:82-92` | `SmartMemoryStrategy.__init__` monkey-patches `get_num_tokens_from_messages` **onto the shared `ChatOpenAI` instance**. `ReviewAgent` later calls that method (`agent.py:286`) and silently receives a `chars/4` estimate instead of a real token count. A memory strategy mutating the model object is a hidden global side effect. |
| F-12 | 🟡 | `openhands/agent/analyzers/semantic_analyzer.py:342-348` | `_is_only_style` compares two empty lists when a diff has no additions or removals and returns `True`, classifying unrelated changes as `STYLE`. |
| F-13 | 🟡 | `openhands/agent/analyzers/semantic_analyzer.py:308-310` | Bug-fix classification triggers on the substring `fix`/`bug`/`error` anywhere in the diff — `prefix`, `debug`, `error_handler` all match. |
| F-14 | 🟡 | `openhands/agent/analyzers/semantic_analyzer.py:395-404` | "Function is defined but never called" is decided from occurrences inside a **single file**. Any function called from another module is reported as orphaned. |
| F-15 | 🟡 | `openhands/agent/main.py:59-60` | `--project-id`/`--mr-iid` use `type=int` with an environment-variable default. argparse does not apply `type` to defaults, so under CI the values stay strings while under manual invocation they are ints. |
| F-16 | 🟡 | `openhands/agent/metrics/collector.py:58-85` | `export_prometheus` only serialises `self._metrics[-1]`. One `ReviewMetrics` is recorded per file, so all but the last file's metrics are discarded. Output also lacks `# HELP`/`# TYPE` lines required by the OpenMetrics text format. |
| F-17 | 🟡 | `openhands/agent/main.py:152-161` | `security_score`, `performance_score`, `critical_issues`, `high_issues` and `medium_issues` are never populated, so the exported metrics always report `0`. README advertises "detailed review metrics". |
| F-18 | 🟡 | `openhands/agent/triage/review_triage.py:412-440` | `triage_changes()` accepts a `TriageConfig`, but `ReviewTriage` probes for `policy.triage`/`policy.security`. A `TriageConfig` fails those checks and silently falls back to two hard-coded patterns. |
| F-19 | 🟡 | `openhands/agent/core/agent.py:232` and `:275` | `load_context()` is called twice; the first result is overwritten unused. |
| F-55 | 🟡 | `openhands/agent/config/config_loader.py:201-240` | `_merge_policies` never applies `version`, so a policy file declaring `version: "2.0"` still reports `1.0` in every merge-request comment and metric. *Found while fixing F-04.* |
| F-58 | 🟠 | `code_reviewer/application/review_service.py` | An exception from the reviewer or an analyzer on one file propagates out of the workflow, so the composition root exits 1 and every completed review is discarded — nothing is posted. One flaky model call costs the whole run. *Found while specifying Level 4.* |
| F-59 | 🟡 | `code_reviewer/infrastructure/llm/vllm.py` | The chat model is constructed with no request timeout and no retry policy. A hung endpoint hangs the pipeline until CI's own timeout kills it, with no output and no indication of why. *Found while specifying Level 4.* |
| F-57 | 🟠 | `openhands/agent/gate/review_gate.py:65` | The gate looked for the literal string `SAST Scan Result: FAIL`, but the prompt asks the model for `- **SAST Scan Result**: FAIL - <level>`. The emphasis markers meant the check never matched anything the agent produced, so a failed security scan on its own could not fail the gate. It appeared to work only because failing reports usually also carry a critical risk assessment. *Found while writing the workflow tests in Level 2.* |
| F-56 | 🟠 | `openhands/agent/config/config_loader.py:238` | A YAML section that is present but empty parses as `None`, and `base.custom_rules.update(None)` raises `TypeError`. The shipped `review_policy.yaml` ends with exactly such a section, so loading the project's own policy file crashed the run. It was invisible only because F-04 meant the file was never loaded. *Found while fixing F-04.* |

## B. Security

| ID | Sev | Location | Finding |
|---|---|---|---|
| F-20 | 🔴 | `openhands/agent/main.py:47` | `gitlab.Gitlab(..., ssl_verify=False)` disables TLS verification for every API call, including the one that carries `GITLAB_TOKEN`. The project's own SAST analyzer flags `verify = False` as HIGH severity, CWE-295. |
| F-21 | 🟠 | `openhands/agent/tools/definitions.py:9-41`, `:175-211` | `read_file`, `list_files`, `grep_search` and `find_references` accept arbitrary paths from model output with no root confinement. A prompt-injected diff can make the agent read `/etc/passwd` or any file the CI runner can reach and echo it into a public merge-request comment. |
| F-22 | 🟡 | `openhands/agent/config/review_policy.yaml:17-20` | `.*\.json$`, `.*\.yaml$`, `.*\.yml$` and `.*\.toml$` are skipped outright. Pipeline definitions, Kubernetes manifests and dependency manifests are exactly where supply-chain and privilege changes hide. |
| F-23 | 🟡 | `openhands/agent/tools/definitions.py:14`, `:113` | Files are opened without an explicit `encoding`, so behaviour depends on the runner's locale. |

## C. Architecture (DDD)

| ID | Sev | Location | Finding |
|---|---|---|---|
| F-24 | 🟠 | package layout | There is no layer separation. `openhands/agent/` mixes domain rules (triage policy, semantic model), application orchestration (`main.py`) and infrastructure (GitLab client, vLLM provider, `subprocess` greps) in sibling folders named after technical roles rather than the domain. |
| F-25 | 🟠 | `openhands/agent/main.py` | A single 150-line function is simultaneously the CLI parser, the GitLab adapter, the orchestration workflow, the report renderer and the exit-code policy. It cannot be unit-tested without a live GitLab. |
| F-26 | 🟠 | `openhands/agent/core/interfaces.py:31` | `MemoryStrategy.get_memory_object()` returns "the underlying LangChain memory object". A framework type leaks through a domain port, inverting the dependency direction the abstraction exists to protect. |
| F-27 | 🟠 | no port for the code forge | GitLab is referenced directly by `main.py`. Supporting GitHub, Bitbucket or a local diff requires editing the orchestrator. |
| F-28 | 🟡 | `sast_analyzer.Severity`, `performance_analyzer.Severity`, `quality_analyzer.IssueSeverity` | Three independent severity enums for one domain concept. Cross-analyzer aggregation, sorting and policy thresholds are impossible without conversion code that does not exist. |
| F-29 | 🟡 | `dependency_tracker.AffectedCode` vs `memory/strategies.AffectedCodeEntry` | The same concept modelled twice with different field names. |
| F-30 | 🟡 | `triage/review_triage.TriageConfig` vs `config/config_loader.TriagePolicy` | Duplicate configuration models for the same rules; only one is wired up (see F-18). |
| F-31 | 🟡 | `openhands/agent/analyzers/quality_analyzer.py:118-122`, `performance_analyzer.py` | Thresholds are class constants. `QualityPolicy` and `PerformancePolicy` exist in the config module but are never passed to the analyzers, so configuring them has no effect. |
| F-32 | 🟡 | `openhands/agent/gate/review_gate.py:47-105` | The gate re-parses the model's prose with regular expressions to recover numbers the analyzers already computed. Structured analyzer output should drive the gate; prose should be a rendering of it. |
| F-33 | 🟢 | package name `openhands` | The distribution is named `enterprise-ai-code-reviewer`, but the import package is `openhands`, which is the namespace of the unrelated All-Hands-AI/OpenHands project. Installing both breaks imports. |
| F-34 | 🟢 | `openhands/agent/main.py:22-29` | `sys.path` is patched at import time to compensate for the package not being installable (no `[build-system]`). |

## D. Testing

| ID | Sev | Location | Finding |
|---|---|---|---|
| F-35 | 🟠 | `tests/` | 10 tests cover 2 of 13 modules. The five analyzers (~2 750 lines, the bulk of the product logic), triage, gate, config loader, metrics and tools have **no tests at all**. |
| F-36 | 🟠 | `tests/unit/test_smart_memory.py:64-88` | `test_summarization_trigger` ends in `if …: pass else: pass`. It asserts nothing and always passes — a test that documents an intention while verifying none of it. |
| F-37 | 🟠 | `tests/unit/test_agent_core.py:6-19` | LangChain modules are replaced in `sys.modules` at import time. This leaks into every test collected afterwards in the same process, making results order-dependent and blocking a straightforward `pytest` run. |
| F-38 | 🟡 | `tests/` | No `tests/__init__.py`, no `conftest.py`, no fixtures, no integration or end-to-end tier. |
| F-39 | 🟡 | `pyproject.toml` | `pytest`/`pytest-cov` are declared but there is no pytest configuration, no coverage threshold, and README documents `unittest` instead. |

## E. Packaging, tooling, repository hygiene

| ID | Sev | Location | Finding |
|---|---|---|---|
| F-40 | 🟠 | `LICENSE` vs `README.md:163` | `LICENSE` contains the **GNU GPL v3** (674 lines) while README links it as "MIT License". `pyproject.toml` declares no license at all. Three sources, two answers. |
| F-41 | 🟠 | `pyproject.toml` | No `[build-system]`, so the project cannot be installed; no `license`, `authors`, `urls` or `classifiers`; no console entry point. |
| F-42 | 🟡 | `pyproject.toml:6` vs `README.md:44` | `requires-python = "==3.12.12"` pins a single patch release, while README promises "Python 3.10+". |
| F-43 | 🟡 | repository root | No `.gitignore` in the import — `__pycache__/`, `.venv/` and the generated `metrics.txt` were all candidates for accidental commits. *(Fixed in the baseline commit.)* |
| F-44 | 🟡 | repository root | `.gitlab-ci.yml` does not exist, although README presents GitLab CI integration as the primary use case. No GitHub Actions workflow either. |
| F-45 | 🟡 | dependencies | `langchain==0.1.0`, `langchain-community==0.0.10`, `openai==1.12.0` are pinned to early-2024 releases with known upstream fixes since. |
| F-46 | 🟢 | repository root | No `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`, or architecture documentation. |
| F-47 | 🟢 | whole codebase | Diagnostics use `print()` with hand-written `[INFO]`/`[ERROR]` prefixes. No `logging`, no levels, no structured fields, no way to quiet the agent in CI. |
| F-48 | 🟢 | whole codebase | No formatter, linter or type checker configured; type hints are partial and `Optional` is often implied by `= None` defaults. |

## F. Documentation accuracy

| ID | Sev | Location | Finding |
|---|---|---|---|
| F-49 | 🟠 | `README.md:110` | `--token-limit <int>` is documented as a CLI option. `main.py` defines no such argument; passing it aborts the run. |
| F-50 | 🟡 | `README.md:52` | `cd openhands` after cloning is wrong — `openhands` is the package directory inside the repository, not the clone target. |
| F-51 | 🟡 | `README.md:109` | "default: built-in `review_policy.yaml`" is untrue (see F-04). |
| F-52 | 🟡 | `README.md:146-161` | The project-structure diagram shows `main.py` and `tests/` at the repository root; both are elsewhere. |
| F-53 | 🟡 | `README.md:26` | "Exports detailed review metrics (scores, duration, issues)" — only duration and a partial quality score are ever populated (see F-17). |
| F-54 | 🟢 | source comments | Comments and docstrings mix Turkish and English inconsistently within the same module, and some ("Basic implementation, could actully use…") are notes-to-self rather than documentation. |

---

## Level assignment

| Level | Findings | Status |
|---|---|---|
| 0 — Foundation & documentation truth | F-40, F-41, F-42, F-43, F-46 *(partial)*, F-49, F-50, F-51, F-52, F-53 | ✅ Resolved |
| 1 — Correctness | F-01, F-02, F-03, F-04, F-05, F-06, F-07, F-08, F-09, F-10, F-11, F-12, F-13, F-14, F-15, F-19, F-20, F-36, F-37, F-55, F-56 | ✅ Resolved |
| 2 — DDD layering | F-24, F-25, F-26, F-27, F-28, F-29, F-30, F-33, F-34, F-38, F-57 | ✅ Resolved |
| 3 — Analyzer accuracy & policy | F-21, F-22, F-23, F-31, F-32 | ✅ Resolved |
| 4 — Observability & resilience | F-16, F-17, F-47, F-58, F-59 | ✅ Resolved |
| 5 — CI/CD & quality gates | F-39 *(partial from L0)*, F-44, F-45, F-48 | 📋 Open |
| 6 — Documentation & productisation | F-46, F-54 | 📋 Open |

Some findings appear in two levels: the first occurrence establishes the
structure, the second completes the behaviour once the structure exists.
