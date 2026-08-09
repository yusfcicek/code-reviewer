# 0015 — Retrieval is hybrid, local, and untrusted

Status: Accepted
Date: 2026-08-09
Level: [13](../roadmap/level-13/spec.md)

## Context

For twelve levels the reviewer saw one diff and one file, and that was the
whole of its evidence. Every question a human reviewer asks second — *is there
already a helper for this, is this the pattern the rest of the codebase uses,
who calls this and what do they assume* — was unanswerable except through
`find_references`, which greps for an exact string and only when the model
thinks to ask.

Adding retrieval means three decisions that are easy to get wrong and expensive
to reverse: how two rankings are combined, what produces the embeddings, and
what trust level retrieved code arrives at.

## Decision

### Rank fusion, not score fusion

BM25 returns unbounded scores whose scale depends on the corpus; cosine returns
[-1, 1]. Normalising them into comparability needs a constant that is right for
one repository and wrong for the next. Reciprocal rank fusion discards the
magnitudes and keeps the order — no weight for anyone to choose, and no
recalibration when the corpus changes.

The property test states it directly: rescaling an input ranking's scores
cannot change the fused order, because the scores never reach the function.

### A hashed embedding by default, behind a port

The default `EmbeddingModel` hashes tokens into a fixed number of buckets with
`blake2b` and normalises. It is worse at meaning than any trained model and
better at everything else: no weights to download, no endpoint to fail, no
non-determinism in CI, and a test suite that still runs in seconds.

`hash()` was not an option — Python salts it per process, so an index built in
one run would not match a query embedded in the next, and the failure would be
silent and intermittent.

The gap this leaves is measured rather than asserted:
`tests/unit/infrastructure/test_retrieval_quality.py` includes two paraphrase
queries that share no token with their answer, and asserts that they are
*missed*. That is the test that will fail, loudly, on the day someone swaps in
a trained adapter — which is the only honest way to state what the swap buys.

### Brute-force search, not an approximate index

HNSW and its relatives earn their complexity above roughly 10⁵ vectors. This
repository indexes to about 2 300 chunks and searches them exhaustively in
milliseconds. Recorded as a decision rather than left as an omission so that
the next person reads it as a choice.

### Retrieved code is untrusted, and best-effort

It reaches the prompt inside `<untrusted_repository_context>`, beside
`<untrusted_diff>` and `<untrusted_file_content>`, with both tag forms escaped
inside the text. Retrieved code lives in the checkout, and the checkout is what
the merge request changed: a pipeline that presents it as trusted context is an
injection channel with an index in front of it
([ADR 0010](0010-untrusted-input-defences.md)).

And it never blocks. An index that cannot be built, a search that raises, an
embedding endpoint that is down — each costs the prompt some context and
nothing else. This is deliberately the opposite of the rule Level 9 applied to
static analysis, where a failed analysis blocks because a gate must not read
"nothing examined" as "nothing found". A prompt with less context in it is
still a prompt.

## Consequences

The review path acquires a per-run indexing cost — about one second for this
repository, and bounded by ceilings on files and chunks that are logged when
they bite. A merge request whose files are all skipped by triage pays it for
nothing, which is the price of building the index before knowing whether it
will be asked.

Two indexes have to be maintained instead of one, and the argument for that is
a measurement rather than a preference: at a cutoff of two over eleven queries,
the lexical half answers 8, the dense half answers 8, and the fusion answers 9.
Each half finds something the other misses. If that stops being true, one of
them should go.

`Reviewer.review_diff` gains a `related` parameter with a default of `None`, so
every existing implementation keeps working and a reviewer with no retriever
behind it stays a complete reviewer.

The `search_related_code` tool required its own module: adding it to
`definitions.py` took that file's quality score below the gate's own threshold,
and the agent reported it against its own source before the change was
committed.
