# Level 13 — Retrieval over the repository

## Problem statement

The reviewer sees one diff and one file. That is the whole of its evidence.

Every question a human reviewer asks second is therefore unanswerable. *Is
there already a helper for this?* *Is this the pattern the rest of the codebase
uses, or the first of its kind?* *Who calls this, and what do they assume?* The
agent has a `find_references` tool, which answers the last question by grepping
for a name — but only when the model thinks to ask, and only for an exact
string.

- **There is no retrieval of any kind.** No index, no embeddings, no semantic
  search. The prompt is assembled from the diff, the file, and a list of
  sibling paths in the same merge request (C-04, C-05).
- **Nothing ranks or diversifies what context is worth spending tokens on.**
  Even the sibling list is unranked: every changed path, in whatever order the
  forge returned them (C-06).
- **The one measurement taken at Level 12 has not been spent.** The harness
  found two things on its first run and this level's whole justification for
  existing rests on it being able to answer "did that change help".

Capabilities addressed: **C-04, C-05, C-06**. Level 12 findings addressed:
**E-01, E-02**.

## Goals

1. The repository is chunked, indexed and searchable — lexically and by
   embedding — with no network call and no external service.
2. Retrieval is hybrid and diversified: two rankings fused, then reduced to a
   set that is not three restatements of one function.
3. The reviewer receives the retrieved context, inside the trust boundary
   Level 8 established, and the agent can also search on its own initiative.
4. E-01 and E-02 are closed, and the evaluation harness says whether closing
   them cost anything.

## Non-goals

- **A hosted vector database.** Qdrant, Vertex Matching Engine and their kin
  are named by every source. Binding to one would undo the ports the first
  eleven levels bought, and would make the test suite depend on a server. The
  `VectorIndex` port is declared and a brute-force in-memory adapter ships
  behind it; a Qdrant adapter is then a sibling module and nothing else changes
  (the same argument [ADR 0002](../../adr/0002-layered-architecture.md) makes).
- **A learned embedding model.** Downloading model weights in CI, or calling an
  embedding endpoint per review, are both real costs with real failure modes.
  The default adapter is a deterministic hashed-token embedding: offline,
  reproducible, no weights. It is a *worse* embedding than a trained one and
  the level says so — but it is a real vector space, the fusion and
  diversification are the parts that are hard to get right, and swapping the
  adapter later changes one constructor call.
- **Approximate nearest neighbours.** HNSW earns its complexity above roughly
  10⁵ vectors. A repository's worth of chunks is two orders below that, and
  brute-force cosine over it is microseconds. Choosing an approximate index at
  this size would be architecture as costume.
- **Indexing anything but the checkout.** No history, no other repositories,
  no issue tracker. Those are Level 14's material.
- **Retrieval-augmented *generation* of fixes.** The agent reviews. It does not
  write patches.

## Behavioural contracts

### C-1 — Source is split into chunks that mean something (C-04)
A Python file is chunked by AST into its top-level functions, classes and
methods, each carrying its path, line span and qualified name. A file that
does not parse — or is not Python — falls back to overlapping line windows.
A chunk is never silently empty and never spans a whole large file.

### C-2 — Lexical search ranks by BM25 (C-06)
An exact identifier is the strongest signal code search has, and an embedding
blurs it. BM25 over tokenised identifiers is the lexical half of the hybrid,
implemented in-tree: it is forty lines and it removes a dependency.

### C-3 — Dense search ranks by cosine over embeddings (C-05)
Chunks are embedded and searched by cosine similarity. The default embedding
is a deterministic hashed-token vector, L2-normalised, so the same input always
produces the same vector and no network is touched.

### C-4 — The two rankings are fused by reciprocal rank (C-06)
Scores from BM25 and from cosine are not comparable — different scales,
different distributions — so they are fused by rank rather than by value.
Reciprocal rank fusion needs no tuning constant per corpus, which is why it is
chosen over a weighted score sum that would need one.

### C-5 — The result is diversified before it is spent (C-06)
Maximal marginal relevance selects the final set, trading relevance against
novelty by a stated λ. Three near-identical chunks are three copies of one
piece of evidence, and the token budget is real.

### C-6 — Retrieved context reaches the reviewer inside the trust boundary (C-04)
The chunks are rendered into the prompt inside a declared untrusted block, the
same way the diff and the file content are. Retrieved code comes from the
repository, and whoever opened the merge request can put anything in the
repository — a retrieval pipeline that presents it as trusted context is an
injection channel with an index in front of it
([ADR 0010](../../adr/0010-untrusted-input-defences.md)).

### C-7 — The agent can search on its own initiative (C-04)
A `search_related_code` tool exposes the same retriever, so the model can ask a
question the automatic query did not cover. It is confined by the same
workspace rules as every other tool.

### C-8 — Retrieval failure costs context, not the review (C-04)
An index that cannot be built, or a search that raises, leaves the review to
proceed with the evidence it had before. Retrieval is an improvement to the
prompt, not a precondition for reviewing, and it must not become one — the
distinction Level 9 drew between analysis (blocks) and narration (warns).

### C-9 — SQL injection is found when the query is built into a local (E-01)
`SAST.SQL_INJECTION` gains an AST pass for Python: a string built by
concatenation, `%` formatting or an f-string containing SQL keywords, assigned
to a local and later passed to `execute`, is reported at the line where the
string was built. The regex rules stay: they cover the single-line form and the
languages without an AST here.

### C-10 — `unreferenced_in_file` fires only where the evidence supports it (E-02)
A public function is called from outside the module that defines it; reporting
it as unreferenced is noise dressed as a finding. The rule narrows to private
symbols — a leading underscore means module scope, so "not referenced in this
file" and "not referenced anywhere" are the same statement.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A module chunks into its functions, classes and methods with correct line spans | Unit test |
| AC-2 | An unparseable file falls back to overlapping windows, and loses nothing | Unit + property test |
| AC-3 | BM25 ranks an exact identifier match above a partial one | Unit test |
| AC-4 | The embedding is deterministic, unit-length, and dimension-stable | Unit + property test |
| AC-5 | Cosine search returns the nearest chunk first | Unit test |
| AC-6 | RRF fuses two rankings, and an item ranked well by both beats one ranked well by either | Unit test |
| AC-7 | RRF is invariant to the input scores' scale | Property test |
| AC-8 | MMR with λ=1 returns pure relevance order; with λ=0 it maximises novelty | Unit test |
| AC-9 | MMR never returns the same chunk twice, and never more than asked | Property test |
| AC-10 | The hybrid retriever excludes the file under review from its own results | Unit test |
| AC-11 | Retrieved chunks reach the prompt inside the untrusted block | Unit test on the agent |
| AC-12 | A retriever that raises leaves the review unchanged and logged | Unit test on the service |
| AC-13 | `search_related_code` returns chunks and is confined to the workspace | Unit test |
| AC-14 | A query built into a local and executed is reported at the build line | Unit test + dataset case |
| AC-15 | A parameterised query is not reported | Unit test + dataset case |
| AC-16 | `unreferenced_in_file` fires for a private symbol and not for a public one | Unit test |
| AC-17 | The evaluation dataset gains cases for both changes, and the floors rise | `test_evaluation_baseline.py` |
| AC-18 | The six checks stay green and coverage holds at its floor | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — Fusion and diversification live in the domain; indexing does not.**
Whether two rankings combine to put chunk A above chunk B is arithmetic over
values, testable with lists of integers. Building an index is I/O over a
filesystem. The first is a rule, the second is an adapter, and the line between
them is the one the whole architecture is drawn on.

**D-2 — Rank fusion, not score fusion.** BM25 returns unbounded scores whose
scale depends on the corpus; cosine returns [-1, 1]. Normalising them into
comparability requires a constant that is wrong for the next repository.
Reciprocal rank fusion discards the magnitudes, which is the point: it is the
choice that does not need tuning, and an untuned system that works is worth
more here than a tuned one that works on one corpus.

**D-3 — The default embedding is hashed, not learned.** It is worse at meaning
and better at everything else: no weights to download, no endpoint to fail, no
non-determinism in CI, and a test suite that runs in seconds. The interesting
engineering — chunking, fusion, diversification, trust boundary, failure
handling — is identical either way, and it is the part that is hard to replace
later. The adapter is one constructor call.

**D-4 — Brute force, not ANN.** See non-goals. Recorded as a decision rather
than an omission so that the next person does not read it as an oversight.

**D-5 — Retrieval is best-effort.** It never blocks, never fails a review, and
never turns into a finding. It is prompt material. Level 9 established that
missing *analysis* blocks because a gate must not read "nothing examined" as
"nothing found"; missing *context* has no such property.

**D-6 — Retrieved code is untrusted.** It is inside the checkout, and the
checkout is what the merge request changed. The alternative — treating indexed
repository content as trusted because it is "ours" — is the exact assumption an
attacker with commit access to a branch is looking for.

**D-7 — E-01 is fixed with an AST pass rather than a better regex.** Following
an assignment is not something a line-oriented pattern can do, and the attempts
that try produce the false positives the evaluation harness now charges for.
The regex rules stay for the single-line form and for the languages this
repository does not parse.

**D-8 — E-02 is narrowed rather than deleted.** A private function referenced
only by its own definition is genuine dead code, and that case is worth
reporting. What was wrong was applying it to public API, where the analyzer's
single-file view cannot see the callers.
