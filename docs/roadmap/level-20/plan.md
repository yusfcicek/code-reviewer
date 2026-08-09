# Level 20 — Plan

Branch: `feature/level-20-governance`, off `development`, merged with `--no-ff`.

## Step 1 — Who made a claim

*Tests* — `tests/unit/domain/test_provenance.py`

- A `Producer` carries a kind, a name and a version; an empty name is refused,
  because "something produced this" is not provenance.
- `Provenance` pairs a producer with the evidence it cited — citations and span
  ids, both identifiers.
- A producer of kind `ANALYZER` is deterministic; one of kind `AGENT` is not,
  and the distinction is a property rather than a convention somebody has to
  remember.

*Change* — `code_reviewer/domain/provenance.py`: `ProducerKind`, `Producer`,
`Provenance`.

## Step 2 — What a run was

*Tests* — `tests/unit/domain/test_run_identity.py`

- AC-7: a `RunIdentity` records the package version, the policy version, the
  model, the prompt fingerprint, the analyzer rule set and the evaluation
  baseline.
- A missing model is recorded as `"none"` rather than omitted — "no model was
  used" is a fact about the review, and an absent field reads as an oversight.
- AC-8, AC-9: `fingerprint(*prompts)` differs for different prompts and is
  stable across processes. Asserted against a literal digest, so a change to
  the hashing itself is a change somebody has to make deliberately.

*Change* — `RunIdentity` and `fingerprint` in the same module.

## Step 3 — The record, and the invariant

*Tests* — `tests/unit/domain/test_decision_record.py`

- AC-3: a blocking record whose blocking findings name an `AGENT` producer is
  **refused at construction**, and the message says which finding and which
  producer.
- AC-4: the same record with analyzer producers is accepted.
- AC-5: a non-blocking record may cite anything — an agent's prose is allowed
  to warn, which is exactly what ADR 0004 says.
- AC-6: a blocking verdict with no findings is refused: something decided, and
  a record that cannot say what is not a record.
- AC-11, AC-12: suppressions and per-agent cost are part of it.
- A record is immutable, and equal by value.
- The summary line names the decider and nothing else.

*Change* — `DecisionRecord`, `SuppressionRecord`, `AgentCost`.

## Step 4 — Assembling it

*Tests* — `tests/unit/application/test_decision_recorder.py`

- A record is built from an outcome, its findings, the policy, the identity and
  the agent totals — with no second pass and no extra call.
- Findings from the analysis suite are attributed to `ANALYZER`; the sandbox
  refusal finding is attributed to the tool that refused.
- AC-14: a sink that raises is logged and the recorder returns normally.
- AC-10: no field of a record built from a review whose diff contains a
  credential-shaped string contains it.

*Change* — `application/governance.py`: the `AuditSink` port and
`DecisionRecorder`.

## Step 5 — Writing it

*Tests* — `tests/unit/infrastructure/test_audit_sink.py`

- AC-13: the record round-trips through `json.dumps` and back into the same
  values.
- The file is written atomically, the way the memory store is: a killed process
  leaves the previous record rather than half of one.
- An unwritable destination is a warning, not an exception.
- Two records in one run append rather than overwrite — a service reviews many
  merge requests, and one file per process would keep only the last.

*Change* — `infrastructure/governance/json_sink.py`: `JsonAuditSink`
(newline-delimited JSON).

## Step 6 — Saying it in the comment

*Tests* — `tests/unit/application/test_report.py` (extended)

- AC-15: the comment carries the policy version, the model, the prompt
  fingerprint, the trace id, and the sentence naming what decided.
- Without an identity the block is absent rather than half-filled.

*Change* — `render_review_comment` takes the identity.

## Step 7 — Wiring

*Tests* — `tests/unit/test_main_wiring.py` (extended)

- AC-16: `--audit-path` builds a sink; without it, none.
- The identity is assembled from the policy, the environment and the prompts
  actually in use.

*Change* — `cli.py`, `__main__.py`, `serve.py`.

## Step 8 — Documentation

- `docs/adr/0022-a-verdict-that-can-be-audited.md`: D-1, D-2, D-3, D-5.
- `docs/ARCHITECTURE.md`, `README.md`, `SECURITY.md`, `CHANGELOG.md`,
  `docs/roadmap/README.md`, and the roadmap's closing note.

## Order and rationale

Step 3 is the level. Everything before it is vocabulary and everything after it
is plumbing; the invariant that a blocking record cannot cite a model is the
one thing here that changes what the system *can* do rather than what it
records.

It is also the last level, so step 8 closes the roadmap: twenty capabilities
from three role descriptions, eight levels, and a note saying which of them are
met and which were deliberately left.
