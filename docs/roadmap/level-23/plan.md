# Level 23 — Plan

Branch: `feature/level-23-documentation-drift`, off `development`, merged with
`--no-ff`.

Order is chosen so that each step is shippable on its own and the model never
enters the picture until the deterministic tier is complete. If the level had to
stop early, it would stop with Tier A working and Tier B absent, which is the
right way round.

## Step 1 — What a document claims

*Tests* — `tests/unit/domain/test_documentation.py`

- A backtick token shaped like a symbol (`create_app`, `AgentExecutor`,
  `module.thing`, `f()`) becomes a claim; AC-2: `async`, `false`, `critical`,
  `auto` do not. The shape test is the whole precision argument — README
  backticks hold prose as often as they hold code.
- A call with arguments (`` `render_review_comment(version, outcome)` ``)
  becomes a signature claim carrying the argument names.
- `--flag` and `SCREAMING_SNAKE` become option claims.
- A fenced ` ```python ` block becomes an example claim carrying its source.
- Every claim carries its line and the nearest preceding heading; a document
  with no heading yields claims with an empty anchor rather than no claims.
- Claims inside a fenced block are not also read as prose claims.

*Change* — `code_reviewer/domain/documentation.py`.

## Step 2 — What the code offers

*Tests* — `tests/unit/domain/test_symbol_index.py`

- A `SymbolIndex` answers `resolves(name)` for a bare name, a dotted path and a
  method on a class.
- `parameters_of(name)` returns the parameter names, `None` when the symbol is
  not a function — the two are different answers and a caller must be able to
  tell them apart.
- An empty index resolves nothing and — AC-8's other half — a rule given an
  empty index reports nothing rather than reporting everything as dead. This is
  the failure mode that would make the level unusable on its first bad day.

*Change* — `SymbolIndex` in `code_reviewer/domain/documentation.py`.

## Step 3 — The deterministic rules

*Tests* — `tests/unit/domain/test_documentation_rules.py`

Every rule is scoped by a `ChangeScope` — what the diff removed, what it
touched, and whether it edited this document. That is not an optimisation: a
first cut resolved every backtick against the tree and produced twenty-five
findings in this repository's README, nearly all wrong, because a library call
and a lost symbol look identical in text. The diff is the only evidence that a
name was ever this project's.

- AC-1: a symbol claim the change *removed* yields `DEAD_REFERENCE`; a name the
  project never owned (`hashlib.md5`, `ConfigMap`) yields nothing, in either
  direction of the scan.
- AC-3: a signature claim whose argument names are not the symbol's yields
  `SIGNATURE_MISMATCH` — checked for a touched symbol or anywhere in an edited
  document. The same claim with the right names yields nothing, and neither does
  a call written with values rather than names (`f(1, 2)`) or a dotted name from
  a library.
- AC-4: an option or environment claim the change *removed* yields
  `UNKNOWN_OPTION`; `--cov` and `--no-ff` yield nothing.
- AC-5: an example that does not `ast.parse` yields `BROKEN_EXAMPLE` in an
  edited document and nothing in an untouched one, and an indented fence is
  dedented before it is parsed.
- AC-8: a correct document over the same index yields nothing at all.

*Change* — `documentation_defects(claims, index, scope)` in the same module.

## Step 4 — The docstring half

*Tests* — `tests/unit/domain/test_docstring_drift.py`

- AC-6: an `Args:` entry naming a parameter the signature does not have.
- The reverse — a documented function missing a parameter — is reported only
  when the docstring documents *some* parameters, because a one-line docstring
  is a style choice rather than a defect.
- AC-7: `Raises:` naming an exception the body never raises, directly or via a
  helper it defines. A function that re-raises what it caught is not reported.
- `Returns:` on a function whose every path returns `None`.
- A file that does not parse yields nothing and says why.
- A docstring with no sections yields nothing.

*Change* — `docstring_defects(source)` in the same module.

## Step 5 — Building the index, and reading the documents

*Tests* — `tests/unit/infrastructure/test_documentation_workspace.py`

- The index is built from the Python tree through `Workspace`, so the path
  guarantees Level 8 bought are not re-implemented here.
- A file that does not parse contributes nothing and does not stop the build.
- `--flags` are collected from `add_argument` calls and environment names from
  `os.environ` / `os.getenv` reads; a name built by string concatenation is not
  collected, and not collecting it is what keeps AC-4 honest.
- Documents are every `.md` under the root, read through the same workspace.

*Change* — `code_reviewer/infrastructure/documentation/workspace.py`, and a
`DocumentationSource` port in `application/ports.py`.

## Step 6 — Tier A, wired to a change

*Tests* — `tests/unit/application/test_documentation_service.py`

- AC-9: a document changed in the same merge request is not reported.
- C-1 both directions: a changed source file is checked for docstring drift; a
  changed document is checked against the index.
- Only documents that make a claim about a symbol the diff touched are scanned;
  a document about something else produces nothing.
- AC-13: every finding is at most `Severity.LOW`, and a test asserts no `DOCS`
  finding can reach `blocking_issues` through the real gate.
- AC-14: no finding's text contains a sentence from the document.
- C-2: an index that did not build yields no findings and one recorded
  degradation.

*Change* — `code_reviewer/application/documentation_service.py`.

## Step 7 — Tier B, retrieved

*Tests* — `tests/unit/infrastructure/test_markdown_chunking.py`,
`tests/unit/application/test_drift_candidates.py`

- AC-10: `chunk_markdown` splits on headings, keeps the heading with its body,
  and falls back to the window chunker for a document with no heading.
- AC-11: a changed function retrieves the section describing it when the
  section never names it — the case the whole tier exists for, tested against a
  fixture written to have no lexical overlap beyond ordinary English.
- AC-16: the candidate cap is applied and the number dropped is returned rather
  than logged and forgotten.
- Candidates below the score floor never reach the model.
- AC-15: a retriever that raises costs the tier and nothing else; the service
  returns the reason the tier did not run.
- AC-12: every finding produced carries the `DRIFT` namespace.

*Change* — `chunk_markdown` in `infrastructure/retrieval/chunking.py`; the
candidate half of `documentation_service.py`; a `DriftJudge` port and its LLM
adapter.

## Step 8 — Attribution, report, record

*Tests* — `tests/unit/application/test_governance.py` (extended),
`tests/unit/application/test_report.py` (extended)

- AC-12: `DOCS` resolves to an analyzer, `DRIFT` to an agent.
- A blocking verdict that cites a `DRIFT` finding is refused — the Level 20
  behaviour, asserted here against the new namespace.
- AC-17: two headings, the second labelled unverified; with nothing to say,
  neither appears and the comment is byte-identical to before.
- AC-18: the record carries rule, location and namespace, no prose.

*Change* — `PRODUCERS`, `_documentation_lines` in `application/report.py`,
`DecisionRecorder`.

## Step 9 — Measured

*Tests* — `tests/unit/test_evaluation_baseline.py` (extended)

- AC-19: `DOCS` joins `REQUIRED_NAMESPACES`; cases are added for a dead
  reference, a signature mismatch and a clean document.
- The `DRIFT` tier is excluded from the precision floor by construction — its
  cases are graded for recall only, and the exclusion is stated in the dataset
  rather than implied by which cases exist.

*Change* — `evaluation/` cases, `REQUIRED_NAMESPACES`.

## Step 10 — Say it once, truthfully

- ADR 0025: two tiers, and why the weaker one is a separate namespace.
- `capability-sources.md`: C-23, with its source named honestly as this
  project's own agreement rather than a role description.
- `README.md`, roadmap `README.md`, `CHANGELOG.md`, version 2.17.0.

The dogfooding gate runs this level against itself, which is the first time
this repository's documentation has been reviewed by it. Whatever it finds is
part of the level, not a follow-up.
