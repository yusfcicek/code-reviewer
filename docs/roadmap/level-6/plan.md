# Level 6 — Implementation Plan

Branch: `feature/level-6-documentation` (off `development`)

## Step 1 — Guard the language boundary

Test-first: `tests/unit/test_documentation.py`.

- No file under `code_reviewer/` contains Turkish-specific characters or the
  common Turkish words that appear in the current comments.
- The test names the offending file and line, so a regression is one grep away
  from fixed.

It fails now, against ten modules.

## Step 2 — Translate, checking each comment against the code

Ten modules, in dependency order so that a corrected term propagates:

`domain/policy.py`, `domain/triage.py`, `domain/gate.py`,
`infrastructure/config/loader.py`, `infrastructure/memory/smart_memory.py`,
then the five analyzers.

Each docstring is read against the function it documents. Comments describing
pre-Level-1 behaviour are rewritten to describe what the code does now
(decision D-2). Terminology follows the domain: *finding*, *severity*,
*triage decision*, *gate*, *outcome*.

**Gate:** 423 tests still pass. A comment change that breaks a test means a
docstring was load-bearing, which is itself worth knowing.

## Step 3 — Architecture document

`docs/ARCHITECTURE.md`:

- the three layers and the dependency rule, with the test that enforces it;
- the ports and their adapters, in a table;
- the path of one review, from `fetch_merge_request` to exit code;
- where to add an analyzer, a forge or a model provider;
- what is deliberately *not* abstracted, and why.

## Step 4 — Decision records

`docs/adr/` with one file per binding decision:

| ADR | Decision | From |
|---|---|---|
| 0001 | MIT licence | Level 0 |
| 0002 | Layered architecture with a one-way dependency rule | Level 2 |
| 0003 | Import package named `code_reviewer` | Level 2 |
| 0004 | The gate decides from findings; prose warns | Level 3 |
| 0005 | Agent file access confined to the workspace | Level 3 |
| 0006 | A failing file is reported, not fatal | Level 4 |
| 0007 | LangChain held at 0.1.x | Level 5 |
| 0008 | English as the language of the source | Level 6 |

Plus `docs/adr/README.md` indexing them.

## Step 5 — Security policy

`SECURITY.md`: supported versions, the threat model (prompt injection through a
diff, what the workspace confines, what reaches a public comment), the
credentials the agent holds, hardening advice for operators, and how to report a
vulnerability.

## Step 6 — Changelog

`CHANGELOG.md` in Keep a Changelog form. One entry per level under `2.0.0`, with
an explicit Breaking section: GPL→MIT, `openhands`→`code_reviewer`, the console
script, the removed metric fields, the new policy keys.

## Step 7 — Link integrity

Extend `tests/unit/test_documentation.py`:

- every relative Markdown link in the repository resolves to a file;
- README links to ARCHITECTURE, SECURITY, CHANGELOG, CONTRIBUTING and the
  roadmap;
- every ADR has Context, Decision and Consequences sections.

## Step 8 — Final sweep and release

- Re-read every file changed across six levels for anything the roadmap missed.
- Update README's status table and structure block.
- Mark Level 6 done; record any finding discovered during the sweep.
- Merge into `development`, then `development` into `main` — the product.

## Risks

| Risk | Mitigation |
|---|---|
| Translation silently changes meaning | Each comment is checked against the code it documents; the suite runs after each module |
| The language test flags legitimate non-ASCII | It targets Turkish-specific characters and words, not all non-ASCII; the review output's emoji and typographic dashes are unaffected |
| ADRs drift from the code | Each cites the level and the tests that hold it in place |
