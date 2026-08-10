# Level 27 — Plan

Branch: `feature/level-27-measured-drift`, off `development`, merged with
`--no-ff`.

Scoring lands first, because the floor needs it and the measurement needs the
floor. The measurement lands before the corpus grows, for the reason Level 25
gave: growing a corpus until a number looks acceptable is not measuring.

## Step 1 — A score on the port

*Tests* — `tests/unit/application/test_scored_retrieval.py`

- AC-1: `CodeRetriever.scored` returns `ScoredChunk`s. The default
  implementation delegates to `related` and marks the results **unscored** — a
  retriever with no notion of a score is a real thing, and a floor over its
  results must report itself as inapplicable rather than passing everything.
  Silence there is how Level 23 lost a whole tier for a whole level.
- AC-2: `HybridRetriever` overrides it and returns the fused scores it already
  computes internally.
- Scores are ordered descending, and the order matches `related`'s.

*Change* — `CodeRetriever` in `application/ports.py`,
`HybridRetriever.scored`.

## Step 2 — A floor Tier B can be held to

*Tests* — `tests/unit/application/test_drift_candidates.py` (extended)

- AC-3: a candidate below the floor never reaches the model.
- AC-4: the number dropped is reported, on the rule Level 23 set about silent
  truncation.
- AC-5: a floor over unscored results reports itself as **not applied**, and the
  candidates pass — which is the old behaviour, now visible instead of implied.
- The floor is a constant with its reasoning beside it, not a parameter with a
  default nobody chose.

*Change* — `application/drift_service.py`.

## Step 3 — Measuring the half that is measurable

*Tests* — `tests/unit/application/test_retrieval_recall.py`

- AC-3 of the spec's C-3: each case names a diff and the document section a
  reader says is related; the measurement is whether that section is retrieved
  and at what rank.
- AC-8: the rank is reported. "It was in the top twenty" and "it was first" are
  different facts about a tier whose cap is three.
- AC-9: a case whose section is not retrieved is named, not averaged.
- A corpus with no cases measures nothing and says so rather than scoring 1.0 —
  the defect Level 25 found in the analyzer harness, not repeated here.

*Change* — `application/retrieval_recall.py`,
`infrastructure/evaluation/retrieval_dataset.py`,
`evaluation/retrieval/*.yaml`.

## Step 4 — The corpus, and the floor it earns

*Tests* — `tests/unit/test_retrieval_baseline.py`

- Cases written from what the tier is for: a document section that describes the
  changed behaviour **without naming the symbol**, which is the case no token
  match reaches and the reason Tier B exists.
- AC-7: recall floored on the interval's lower bound, per Level 25.
- The floor is whatever the corpus supports. If that is a low number, it is a
  low number.
- `evaluate --retrieval` runs it, with the three exit codes.

*Change* — `evaluation/retrieval/`, `evaluate.py`.

## Step 5 — More than one language

*Tests* — `tests/unit/infrastructure/test_symbol_index_languages.py`

- AC-10: a declaration in Go, JavaScript/TypeScript and Java produces a
  resolvable name. Chosen because the retrieval corpus already indexes those
  suffixes and because they are what the sources this roadmap came from name.
- AC-11: a language with no pattern contributes nothing, and the covered set is
  a stated constant rather than an implication.
- A file that does not match anything contributes nothing and does not stop the
  build — the rule every indexer here already follows.
- The Python path is unchanged, asserted by the existing tests.

*Change* — `infrastructure/documentation/workspace.py`.

## Step 6 — The one documentation edit that is arithmetic

*Tests* — `tests/unit/domain/test_documentation_recipes.py`

- AC-12: the diff removed `start_app` and added `create_app` in one file, a
  document names `start_app`, and the suggestion substitutes it.
- AC-13: two removals and two additions is ambiguous, and ambiguous yields
  nothing.
- A rename with no document naming the old name yields nothing.
- AC-14: a test asserts no documentation suggestion can come from a model —
  the same parse-the-module assertion Level 22 used for its no-write claim.

*Change* — `domain/documentation.py`, `application/documentation_service.py`.

## Step 7 — Answer the blocking question with the number

*Tests* — `tests/unit/test_documentation_baseline.py` (extended)

- Measure `DOCS` over the corpus it has. State what that supports.
- If it does not support blocking, the report names the corpus that would, and
  the severity stays where it is. A level that raises a floor it did not earn is
  the thing this project has refused since Level 12.

*Change* — the report, and the spec's C-8 answered rather than restated.

## Step 8 — Say it once, truthfully

- ADR 0029: measure the half that is measurable, and what a score on a port
  buys.
- `capability-sources.md`: C-32, C-33, C-34 from Level 23's non-goals.
- README, CHANGELOG, version 2.21.0.

The dogfooding gate runs this level against itself; whatever it finds is part of
the level.
