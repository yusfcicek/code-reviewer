# Level 7 — Implementation Plan

Branch: `feature/level-7-dependency-upgrade` (off `development`)

Ordered so that the security benefit lands first and the riskiest change lands
last, behind tests that already pass. Every step states the test that must fail
before the code is written.

## Step 1 — Measure before changing (G-15)

`scripts/audit-deps.sh` plus a `pip-audit` dev dependency and a CI step.

The script wraps `pip-audit` because it exits `1` for both a real advisory and
a network failure (decision D-5): output matching a known-vulnerability marker
fails immediately, anything else retries with backoff up to three attempts. The
ignore list is empty and the script says so.

**Gate:** the script runs locally and its output is recorded here as the
level's before-figure. It is expected to be red — that is the point of running
it first.

**Before-figure, measured on this branch:**

```
Found 59 known vulnerabilities in 11 packages
```

across `aiohttp`, `idna`, `langchain`, `langchain-community`, `langchain-core`,
`langchain-openai`, `langsmith`, `pygments`, `pytest`, `requests` and
`urllib3`. Six of the eleven arrive through the LangChain 0.1 pin and one of
those — `aiohttp` — arrives only through `langchain-community`, which nothing
imports.

## Step 2 — Drop `langchain-community` (G-01)

Test-first: `tests/unit/test_dependencies.py` asserts that no module under
`code_reviewer/` or `tests/` imports `langchain_community`, and that it does not
appear in `pyproject.toml`.

It fails on one import: `tests/integration/test_agent_tool_loop.py` uses
`FakeListChatModel`. Replace it with a local scripted stub (decision D-6),
which the later steps need anyway to express a native `tool_calls` response.

**Gate:** the dependency test passes; the integration test still passes; the
audit re-run shows the advisories that left with the package.

## Step 3 — The parser, both protocols (G-02, C-1, C-2)

New module `code_reviewer/infrastructure/llm/tool_calls.py`.

Test-first: `tests/unit/infrastructure/test_tool_calls.py`

| Test | Asserts |
|---|---|
| native call | A response with `tool_calls` yields the name, args and call id |
| hermes single | One `<parameter=>` block yields one argument |
| **hermes multi** | Two blocks yield **two** arguments — fails today |
| hermes whitespace | Values are stripped; newlines inside a value survive |
| no call | Plain text yields a final answer carrying the text |
| both present | The native field wins |
| malformed xml | An unclosed `<tool_call>` is a final answer, not a crash |

`ToolInvocation` is a frozen dataclass: `name`, `arguments`, `call_id | None`.
The `call_id` matters — a native tool result must come back as a `ToolMessage`
carrying `tool_call_id` or the server rejects the conversation.

## Step 4 — The loop (G-02, G-14, C-4, C-5)

New module `code_reviewer/infrastructure/llm/narration_loop.py`.

Test-first: `tests/unit/infrastructure/test_narration_loop.py`

| Test | Asserts |
|---|---|
| terminates | A response with no tool call returns its text |
| one round | A tool call runs the tool, then the next response is returned |
| observation shape | A native call's result is a `ToolMessage` with the id; a Hermes call's is a plain message |
| unknown tool | Observation names the tool and lists what exists; the loop continues |
| raising tool | Observation carries the error; the loop continues |
| iteration cap | The loop stops after N rounds and returns the last text |
| truncation | An observation over the limit ends with a marker naming the dropped count |
| time budget | Off by default; when set, the loop stops at the deadline |

Bounds are constructor arguments with environment-backed defaults
(`REVIEW_MAX_ITERATIONS`, `REVIEW_MAX_SECONDS`, `REVIEW_MAX_OBSERVATION_CHARS`),
so the tests set them directly and never touch the environment.

## Step 5 — Bind tools by protocol (G-02, C-3)

Test-first: `tests/unit/infrastructure/test_review_agent.py` gains cases for
`REVIEW_TOOL_PROTOCOL`:

- `auto`: `bind_tools` is called; when it raises, the unbound model is used and
  a warning is logged;
- `native`: `bind_tools` is called; when it raises, so does construction;
- `hermes` / `none`: `bind_tools` is not called. Under `none` the catalogue
  says the model has no tools.

## Step 6 — Swap the executor out (G-02, D-4)

`ReviewAgent` constructs `NarrationLoop` instead of `AgentExecutor`, and
`review_diff` calls `loop.run(messages)`.

`HermesToolOutputParser`, `format_to_hermes_messages` and the `AgentExecutor`
wiring are deleted. `render_tool_catalogue` stays — it is what the Hermes path
offers, and under `none` it is what tells the model it has none.

**Gate:** the rewritten `tests/integration/test_agent_tool_loop.py` drives the
whole path twice, once per dialect, including a two-argument call. The 433
existing tests still pass.

## Step 7 — Upgrade LangChain (G-01)

Only now, with the loop under test and the executor gone, does the version
constraint move: `langchain`, `langchain-core`, `langchain-openai` and `openai`
to their current majors, `python-gitlab` to a range rather than an exact pin.

Expected fallout, in the order it will appear:

1. `from langchain.tools import StructuredTool` → `langchain_core.tools`.
2. `from langchain.agents import ...` — gone, and by this step unused.
3. `ChatOpenAI` constructor arguments in `infrastructure/llm/vllm.py`.
4. `get_num_tokens_from_messages` behaviour in `token_counter.py`.

**Gate:** `pytest`, then `./scripts/audit-deps.sh` green with an empty ignore
list. The before/after advisory counts go in the level's completion note.

## Step 8 — Documentation and records

- ADR `0009-agent-loop-in-tree.md`: why the loop is ours, superseding
  ADR 0007. Mark 0007 superseded rather than deleting it.
- `README.md`: the tool-protocol table, the new environment variables, and the
  cost note — with tools bound the model actually reads files, so a review
  takes materially longer, and `none` is a legitimate choice when only the
  deterministic gate is wanted.
- `SECURITY.md`: the audit's empty ignore list and the rule for adding to it.
- `CHANGELOG.md`: breaking — the removed `langchain-community` dependency, the
  removed `HermesToolOutputParser` symbol, the new environment variables.
- `docs/roadmap/README.md`: Level 7 in the table; F-45 moves out of the
  deferred section with a pointer to this level.

## Verification

Run in this order; each is a gate for the next.

```bash
uv run ruff check code_reviewer tests
uv run ruff format --check code_reviewer tests conftest.py
uv run mypy
uv run pytest --cov
./scripts/audit-deps.sh
```

## Risk register

| Risk | Mitigation |
|---|---|
| The LangChain major breaks something no test covers | Step 7 is last; every other change is already green before the version moves |
| The upgrade cascades into `vllm.py` and `token_counter.py` | Both are small and both have unit tests (`test_vllm.py`, they pin the provider's construction) |
| Removing `AgentExecutor` loses retry-on-parse-error behaviour | `handle_parsing_errors=True` is replaced by C-5: an unparseable response is a final answer, and a failing tool is an observation |
| The audit is red for a reason this level cannot fix | It is recorded in `SECURITY.md` with a reason and an ignore entry, per D-5 — not silenced |
