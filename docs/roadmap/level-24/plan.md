# Level 24 — Plan

Branch: `feature/level-24-audit-integrity`, off `development`, merged with
`--no-ff`.

Ordered so that the integrity half is complete and shippable before the
compliance half begins, and so that erasure — the one operation that writes over
existing records — arrives last, when the verifier that proves it correct
already exists.

## Step 1 — What a sealed record is

*Tests* — `tests/unit/domain/test_audit_seal.py`

- A `Seal` carries the previous record's digest, the digest of this record, a
  key id and a signature; a seal with a signature and no key id is refused at
  construction, because it reads as verified and names nothing.
- `GENESIS` is a stated constant, not an empty string: "this is the first
  record" and "somebody removed the field" must be different states (AC-4).
- `digest_of(payload)` is stable across dict ordering — the record is
  serialised with sorted keys already, and the digest has to agree with that
  rather than with insertion order.
- A seal over an empty payload is refused.

*Change* — `code_reviewer/domain/audit.py`.

## Step 2 — Chaining, and what a broken chain looks like

*Tests* — `tests/unit/domain/test_audit_chain.py`

- `verify(seals)` returns a verdict naming the **first** failing position and
  the reason (AC-4 to AC-9), never a boolean.
- AC-5: a payload edited by one character fails at its own line.
- AC-6: a deleted line fails at the *following* line, and the message says the
  chain broke rather than that a signature was wrong — the two are different
  events and an operator needs to know which.
- AC-7: two lines swapped are detected.
- AC-9: seals with no signature verify their *chain* and report
  `unverifiable` for their signatures. Not `tampered`. This is the state a
  deployment that has not configured a key is in on its first day, and crying
  wolf there is how the tool gets turned off.
- An empty store is intact rather than an error.

*Change* — `verify` and `ChainVerdict` in the same module.

## Step 3 — The signer, and the refusal to invent a key

*Tests* — `tests/unit/application/test_signing.py`,
`tests/unit/infrastructure/test_hmac_signer.py`

- The `Signer` port signs bytes and names its key; `NullSigner` signs nothing
  and says so, which is what a deployment with no key gets (AC-2).
- AC-19: the key never appears in `repr`, in a log record, or in anything
  rendered. Asserted by building a signer with a credential-shaped key and
  searching every artefact for it — the test Level 20 wrote for records,
  applied to the thing that would actually be a credential.
- The HMAC adapter reads its key from the environment and **refuses to
  construct** without one rather than defaulting.
- A key shorter than the minimum is refused with a reason that does not quote
  it.
- AC-3: a signer that raises leaves the record written and unsigned.

*Change* — `Signer` in `application/ports.py`,
`infrastructure/governance/signing.py`.

## Step 4 — A sink that seals what it writes

*Tests* — `tests/unit/infrastructure/test_sealed_sink.py`

- Each line carries its seal; the first carries `GENESIS`.
- The previous digest is read from the **file**, not from memory, so a process
  restart continues the chain rather than starting a second one.
- A store the sink cannot read starts a new chain and says so, rather than
  writing a line whose predecessor is a guess.
- AC-10: a thousand records verify, and the test measures that verification is
  linear rather than quadratic — a verifier nobody can afford to run is a
  verifier nobody runs.
- Concurrent writers: the append is already atomic per line; the digest read
  is not, and the test states what the sink does about it rather than leaving
  it to be discovered.

*Change* — `infrastructure/governance/sealed_sink.py`.

## Step 5 — The verifier as a command

*Tests* — `tests/unit/test_audit_cli.py`

- `ai-code-review-audit verify --path …` exits `0` intact, `1` tampered, `2`
  unverifiable or unreadable. The same three-exit-code shape `evaluate` uses,
  for the same reason: a pipeline has to tell a bad answer from a broken tool.
- The report names the position and the reason and prints no record content.
- A missing file is `2`, not `1`.

*Change* — `code_reviewer/audit.py`, a console entry point.

## Step 6 — The control mapping

*Tests* — `tests/unit/test_control_mapping.py`

- AC-11: every namespace the suite emits, plus `DOCS`, `DRIFT` and `SANDBOX`,
  resolves to at least one control. The same completeness test Level 20 wrote
  for the attribution table, which is what makes a new namespace a red test
  rather than a silent omission.
- The file states the catalogue's name, version and publisher, and a test
  asserts all three are present and non-empty.
- AC-12: an unmapped namespace renders as unmapped.
- AC-13: the word "compliant" does not appear in the rendered output, and
  neither does "certified".
- A control with no evidence in this run renders as *no evidence*, which is the
  answer an auditor actually needs.

*Change* — `evaluation/../compliance/controls.yaml`
(a data file, replaceable), `application/compliance.py`.

## Step 7 — Retention and erasure

*Tests* — `tests/unit/application/test_erasure.py`

- AC-14: erasing by age removes the intended records, and the rewritten store
  verifies end to end.
- AC-15: each removal leaves a tombstone naming the position, the time and the
  policy — erasure and tampering must stay distinguishable, which is the whole
  reason this is not a `sed` command.
- AC-16: redacting a subject (a project, a merge request) empties the fields
  that name it and leaves the record's shape and verifiability intact.
- AC-17: nothing erases without an explicit command. A test runs a review and
  asserts the store is append-only in practice.
- An erasure that cannot re-sign — no key — refuses rather than producing an
  unverifiable store.

*Change* — `application/erasure.py`, `audit erase` and `audit redact`.

## Step 8 — Wired, and outside the verdict

*Tests* — `tests/unit/test_main_wiring.py` (extended)

- AC-18: a signer that raises, a verifier that is never called and a mapping
  that fails to load each leave the exit code untouched.
- `--audit-key-env` names the variable; absent, records are unsigned.

*Change* — `__main__.py`, `cli.py`.

## Step 9 — Say it once, truthfully

- ADR 0026: detection rather than prevention, and the sentence that says what
  this does not buy.
- `capability-sources.md`: C-24, C-25, C-26, sourced from Level 20's non-goals.
- `README.md`, roadmap `README.md`, `CHANGELOG.md`, version 2.18.0.

The dogfooding gate runs this level against itself. Whatever it finds is part of
the level.
