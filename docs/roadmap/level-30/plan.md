# Level 30 — Plan

Branch: `feature/level-30-key-custody`, off `development`, merged with `--no-ff`.

The order is the domain first, because the defect is in what a boolean can say.

## Step 1 — Three answers where there were two

*Tests* — `tests/unit/domain/test_audit_chain.py` (extended)

- `accepts` returns `bool | None`: `None` means *I hold no key with that name*.
- `verify` reads `None` as unverifiable and carries on: the links still hold, and
  a chain whose links hold is not a forged chain.
- The verdict names the key ids it could not check (C-5).
- A wrong signature under a held key is unchanged (C-3).

*Change* — `code_reviewer/domain/audit.py`.

## Step 2 — The keyring

*Tests* — `tests/unit/infrastructure/test_signing.py` (extended)

- `Keyring(signing, retired)`: signs with the current key, verifies with any.
- Every refusal `HmacSigner` makes applies to a retired key (C-6), and the key
  material never escapes — the five tests Level 24 wrote, over the retired keys
  too (AC-8).
- `signer_from_environment` learns `REVIEW_AUDIT_KEY_RETIRED_<ID>`: one variable
  per key, so nothing is parsed out of secret material (D-4).

*Change* — `code_reviewer/infrastructure/governance/signing.py`.

## Step 3 — What the operator sees

*Tests* — `tests/unit/test_audit_cli.py` (extended)

- A store signed under a key that is gone reports **unverifiable** and names the
  key, rather than accusing somebody of a tamper (AC-12).
- Exit codes unchanged: the tool's three meanings are Level 24's.

*Change* — `code_reviewer/audit.py`, `sealed_sink.py`.

## Step 4 — The store contract, since the store is refused

*Tests* — `tests/unit/test_store_conformance.py`

- One suite, parameterised over adapters, asserting what any `AuditStore` must
  do: read back in written order, hold every record, report a truncated store
  as truncated, distinguish absent from empty.
- `FileAuditStore` passes it (AC-9). Two deliberately broken in-memory adapters
  — one that reorders, one that drops the last write — fail it (AC-10), because
  a conformance suite nothing fails is the shape self-review 27 was about.

*Change* — the test module, and whatever the suite proves is missing from the
port's documentation.

## Step 5 — The premise under the encryption refusal

*Tests* — `tests/unit/domain/test_provenance.py`

- Every field a `DecisionRecord` carries, read and checked: identifiers, counts,
  verdicts, reasons somebody typed. Nothing that could be a line of source.
- The test is the refusal's premise, so the refusal stops being a habit (C-8).

## Step 6 — Say it once, truthfully

- ADR 0032: a key that is gone is not a key that lied.
- `capability-sources.md`: C-37.
- README, CHANGELOG, version 2.24.0, and the three refusals written where a
  reader will find them rather than only in this plan.

The dogfooding gate runs this level against itself.
