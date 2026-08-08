# Level 8 — Implementation Plan

Branch: `feature/level-8-untrusted-input` (off `development`)

Ordered smallest-blast-radius first. Each step is independently shippable, so a
step that turns out larger than expected does not hold the others hostage.

## Step 1 — A search pattern is data (G-06, C-7)

New module `code_reviewer/infrastructure/tools/safe_search.py`.

Test-first: `tests/unit/infrastructure/test_safe_search.py`

| Test | Asserts |
|---|---|
| fixed string | The command contains `-F` |
| separator | `--` precedes the pattern |
| bound | `--max-count=N` is present |
| excludes | `.env`, `*.pem`, `*.key` are excluded, alongside build directories |
| leading dash | A pattern starting `-` is refused |
| control characters | A newline or NUL in the pattern is refused |
| traversal | `..` in the pattern is refused |
| length | An over-long pattern is refused |
| valid symbols | `handle_request`, `My::Type`, `a.b.c`, `file-name.h` all pass |

`CodeSearchTools.grep_search` then builds its command through it. The refusal
comes back as text the model can act on, matching how `OutsideWorkspaceError`
is already surfaced.

## Step 2 — File access is denied by name, budgeted and recorded (G-05, C-3…C-5)

Extend `code_reviewer/infrastructure/tools/workspace.py`.

Test-first: `tests/unit/infrastructure/test_workspace.py` gains

| Test | Asserts |
|---|---|
| deny by name | `.env`, `id_rsa`, `credentials`, `.netrc` are refused |
| deny by glob | `key.pem`, `server.key`, `cert.p12` are refused |
| deny nested | `config/.env` is refused |
| deny `.git` | Anything under `.git/` is refused |
| listing | A listing omits denied entries rather than naming them |
| per-file cap | An oversized file is still truncated, as before |
| total budget | Reads are refused once the budget is exhausted |
| budget accounting | The recorded total matches what was read |
| NUL byte | A path containing `\x00` is denied and recorded, not raised |
| audit log | An allowed read and a refused one both appear, with reasons |
| violations | `violations` returns only the refused ones |

The existing containment tests must keep passing untouched — that behaviour is
not what changes (decision D-5).

## Step 3 — Refusals become findings (C-6, D-3, D-4)

Three small pieces, in dependency order.

1. `application/ports.py` gains `AccessAuditor`, an ABC with `violations()`
   returning a sequence of records carrying `path` and `reason`.
2. `ReviewService` takes an optional auditor. After the reviewer has run for a
   file, any violations recorded *during that file* are translated into
   `Finding(category=SECURITY, severity=CRITICAL, rule_id="sandbox_violation")`
   and joined to the analyzer's findings, so the gate sees them.
3. The composition root passes the `Workspace`.

Test-first: `tests/unit/application/test_review_service.py` gains a fake
auditor and asserts

- a violation during a file produces a CRITICAL finding on that file;
- the finding names the path that was refused;
- a violation recorded before this file is not attributed to it;
- no auditor means no change in behaviour.

**Gate:** an injection attempt in a fixture diff drives the outcome to `FAIL`.

## Step 4 — The review text is redacted (G-04, C-2)

New module `code_reviewer/infrastructure/security/redaction.py`.

Test-first: `tests/unit/infrastructure/test_redaction.py`

| Test | Asserts |
|---|---|
| env value | A `GITLAB_TOKEN` value is masked wherever it appears |
| env value, short | A value under the floor is left alone (decision D-2) |
| private key | A `BEGIN…END PRIVATE KEY` block is masked whole |
| cloud keys | `AKIA…`, `glpat-…`, `ghp_…`, `sk-…`, `xox…` |
| bearer | `Authorization: Bearer …` masks the credential, not the header |
| assignment | `api_key = "…"` masks the value, not the key name |
| prose | Ordinary review text is unchanged |
| count | The number of masked spans is reported |
| empty | Empty input is handled |

Applied at one place: the value `ReviewAgent.review_diff` returns. One place,
because a redactor applied at three is a redactor with two places left to
forget.

## Step 5 — The trust boundary (G-03, C-1)

`ReviewAgent`: a `_sanitise_untrusted` helper, the tags around diff and file
content, and a `TRUST BOUNDARY` section at the top of `SYSTEM_TEMPLATE`.

Test-first: `tests/unit/infrastructure/test_review_agent_prompt.py` gains

- the diff is wrapped in `<untrusted_diff>`;
- the file content is wrapped in `<untrusted_file_content>`;
- a diff containing `</untrusted_diff>` comes out escaped;
- a diff containing `<untrusted_diff>` comes out escaped too — an opening tag
  is as good as a closing one for confusing the boundary;
- the system prompt names both tags and forbids following instructions inside
  them.

The section goes at the *top* of the template, before the operational strategy.
A trust rule stated after five hundred words of instructions is a trust rule
competing with them.

## Step 6 — Documentation

- ADR `0010-untrusted-input-defences.md`: the four layers, and why a refused
  read is a finding rather than a paragraph.
- `SECURITY.md`: rewrite the prompt-injection section against what now exists —
  the tags, the deny-list, the budget, the audit log — and state plainly what
  is still not defended.
- `README.md`: the confinement section, the new environment variables, and the
  fact that a refusal blocks.
- `CHANGELOG.md`: added defences; the new `AccessAuditor` port.

## Verification

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
| The deny-list refuses a file a legitimate review needs | It covers credential-bearing names only. `.env.example` is caught by `.env.*` and that is the correct trade: a review of an example file is worth less than a leaked real one |
| Refusals blocking the pipeline surprises people | It is a CRITICAL finding, so `gate.blocking_severity` governs it like any other, and the reason names the path |
| Redaction mangles a legitimate review | The value layer has a length floor (D-2) and the shape patterns are anchored; a test asserts ordinary prose is untouched |
| The total read budget cuts a large review short | The default is generous, it is configurable, and exhausting it is recorded as a violation rather than silently returning nothing |
