# Level 13 — Plan

Branch: `feature/level-13-retrieval`, off `development`, merged with `--no-ff`.

Steps 1 and 2 come first deliberately: they are the level's proof that Level 12
was worth building, and they are measured by it before anything else changes.

## Step 1 — Spend the instrument: E-01

*Tests* — `tests/unit/infrastructure/test_sql_taint.py`

- AC-14: a query concatenated into a local and executed is reported at the
  line where the string was built, not where `execute` was called.
- The same for `%` formatting, for `.format()`, and for an f-string.
- AC-15: a parameterised `execute("… ?", (value,))` is not reported.
- A literal SQL string with no interpolation, assigned and executed, is not
  reported. Constant SQL is how the safe version looks.
- Concatenation of two literals is not reported: nothing untrusted enters.
- Reassignment through a second local is followed one hop.
- A file that does not parse contributes nothing and raises nothing.
- The existing single-line regex finding and the AST finding at the same line
  collapse to one, because the suite deduplicates by rule and location.

*Change* — `code_reviewer/infrastructure/analyzers/sql_taint.py` with
`find_sql_taint(source) -> list[TaintedQuery]`, called from `SASTAnalyzer.analyze`
for Python only. Kept in its own module so the regex tables stay readable.

## Step 2 — Spend the instrument: E-02

*Tests* — `tests/unit/infrastructure/test_semantic.py` (extended)

- AC-16: a changed private function referenced only by its definition produces
  `unreferenced_in_file`.
- A changed public function referenced only by its definition produces nothing.
- A private function that *is* referenced produces nothing.

*Change* — the integrity check narrows to names beginning with `_`, and the
description says why that is the case where the evidence holds.

## Step 3 — Re-measure

*Change* — `evaluation/cases/sql-injection.yaml` now expects the line-11
finding that E-01 closes; a new `parameterised-query` case with an empty
expectation and full scope, which is where a taint pass earns its false
positives if it is going to; `breaking-change.yaml` widens to `SEMANTIC.*` now
that E-02 no longer fires on it.

*Test* — `tests/unit/test_evaluation_baseline.py`: the floors rise. Written
after the measurement, per Level 12's decision D-4, and the new numbers are
recorded in `baseline.md` beside the old ones.

## Step 4 — The retrievable unit

*Tests* — `tests/unit/domain/test_retrieval_chunks.py`

- A `CodeChunk` knows its path, line span, name and text, and renders a
  citation (`path:start-end`).
- Two chunks with the same path and span are equal and hash alike, so a fused
  ranking can deduplicate.
- An empty chunk is refused at construction: an index full of empty strings
  scores nothing and hides the bug that produced it.

*Change* — `code_reviewer/domain/retrieval.py`: `CodeChunk`, `ScoredChunk`.

## Step 5 — Fusion and diversification

*Tests* — `tests/unit/domain/test_retrieval_ranking.py`

- AC-6: an item ranked 2nd and 3rd beats one ranked 1st and 20th.
- AC-7 (property): multiplying every score in an input ranking by a positive
  constant does not change the fused order.
- Fusion over one ranking preserves that ranking's order.
- Fusion over no rankings returns nothing rather than raising.
- AC-8: MMR at λ=1 is relevance order; at λ=0 the second pick is the one least
  like the first.
- AC-9 (property): MMR returns no duplicates, never exceeds the limit, and
  returns everything when the limit exceeds the candidate count.
- Cosine similarity: orthogonal is 0, identical is 1, a zero vector is 0 and
  not a `ZeroDivisionError`.

*Change* — `reciprocal_rank_fusion`, `maximal_marginal_relevance`,
`cosine_similarity` in the same module.

## Step 6 — Ports

*Change* — `application/ports.py`: `EmbeddingModel`, `LexicalIndex`,
`VectorIndex`, and `CodeRetriever` — the one the workflow depends on, whose
whole surface is `related(query, limit, exclude_path) -> list[CodeChunk]`.

## Step 7 — Chunking

*Tests* — `tests/unit/infrastructure/test_chunking.py`

- AC-1: a module chunks into its functions, its classes and their methods,
  with line spans that match the source.
- A method is chunked once, as part of its class *and* on its own, and the two
  are distinguishable by name.
- AC-2: a file with a syntax error falls back to overlapping windows.
- AC-2 (property): concatenating the windows covers every line of the input.
- A non-Python file uses windows.
- An empty file yields nothing rather than one empty chunk.

*Change* — `infrastructure/retrieval/chunking.py`.

## Step 8 — The two indexes

*Tests* — `tests/unit/infrastructure/test_lexical_index.py`,
`tests/unit/infrastructure/test_embedding.py`,
`tests/unit/infrastructure/test_vector_index.py`

- AC-3: an exact identifier match outranks a partial one; a term in every
  document ranks nothing, because IDF is what BM25 is for.
- Tokenisation splits `snake_case`, `camelCase` and dotted paths, and keeps the
  original token too — `get_user` should be findable as `get_user`, `get` and
  `user`.
- AC-4: the embedding is deterministic across processes, unit length, and the
  same dimension for every input including the empty string.
- AC-5: cosine search returns the nearest first, and an empty index returns
  nothing.
- Searching for more than the index holds returns what there is.

*Change* — `infrastructure/retrieval/lexical.py` (BM25),
`infrastructure/retrieval/embedding.py` (`HashingEmbedding`),
`infrastructure/retrieval/vector_index.py` (`InMemoryVectorIndex`).

## Step 9 — The hybrid retriever

*Tests* — `tests/unit/application/test_hybrid_retriever.py`

- Both indexes are searched, and the result is their fusion, diversified.
- AC-10: a chunk from the file under review is excluded — the reviewer already
  has that file in full, and spending tokens re-showing it is the one certain
  waste.
- A limit of zero returns nothing without searching.
- An index that raises degrades to the other index's result rather than
  failing (C-8 in miniature).

*Change* — `application/retrieval_service.py`: `HybridRetriever`
implementing `CodeRetriever`.

## Step 10 — Building the index from the checkout

*Tests* — `tests/unit/infrastructure/test_corpus.py`

- Every source file under the workspace is chunked and indexed.
- The deny-list and the size limits `Workspace` enforces are respected, so
  `.env` is not indexed and a 10 MB generated file does not become 4 000
  chunks.
- A file that cannot be read is skipped with a log line, not an exception.
- Building over an empty directory produces an empty, usable retriever.

*Change* — `infrastructure/retrieval/corpus.py`: `build_retriever(workspace)`.

## Step 11 — Into the prompt, and into the agent's hands

*Tests* — `tests/unit/infrastructure/test_review_agent_prompt.py` (extended),
`tests/unit/infrastructure/test_tool_calls.py` (extended),
`tests/unit/application/test_review_service.py` (extended)

- AC-11: retrieved chunks appear in the prompt inside a declared untrusted
  block, with their citations, and both tag forms are escaped inside the text.
- AC-12: a retriever that raises leaves the review text unchanged, records a
  log line, and does not produce a finding.
- AC-13: `search_related_code` returns citations and text, and is bounded in
  count and in characters.
- The workflow passes the retriever's output to the reviewer, and passes
  nothing when no retriever is configured.

*Change* — `Reviewer.review_diff` gains a `related` argument with a default of
`None`; `ReviewAgent` renders it; `ReviewService` takes an optional
`CodeRetriever`; `__main__.py` builds one; `tools/definitions.py` gains the
tool.

## Step 12 — Retrieval quality, measured

*Test* — `tests/unit/infrastructure/test_retrieval_quality.py`

A small corpus with known answers: recall@5 for six queries, scored with
`ConfusionMatrix` from Level 12 so the same vocabulary is used for retrieval as
for findings. A floor is asserted, and the hybrid must beat both halves alone —
which is the only evidence that fusing them was worth the code.

## Step 13 — Documentation

- `docs/ARCHITECTURE.md`: the retrieval path, the three new ports.
- `README.md`: what is indexed, what is not, and the trust boundary.
- `docs/adr/0015-retrieval-is-hybrid-local-and-untrusted.md`: D-2, D-3, D-6.
- `docs/roadmap/level-12/baseline.md`: the second measurement.
- `CHANGELOG.md`.

## Order and rationale

Steps 1–3 are first because a measurement nobody acts on was not worth taking,
and because the two fixes are the smallest possible demonstration that the
harness works in both directions: E-01 should raise recall, and the new
`parameterised-query` case is where the fix would show up as lost precision if
it overreached.

Steps 4–6 are pure domain and ports. Steps 7–10 build outwards from there, each
testable alone. Step 11 is the only one that touches the existing review path,
and it is deliberately late: everything it wires together is already proven by
then. Step 12 is last because it measures the whole assembly, and it can only
be honest once the assembly exists.
