"""Step 7 — retention and erasure, without laundering a tamper.

A deletion that leaves a hole is indistinguishable from an attack, which would
make the verifier useless in exactly the deployments that have a legal reason to
delete. So erasure **rewrites** the chain under the key and leaves a tombstone
at each removed position: the store still verifies, and the gap is marked as a
deliberate act with a policy behind it.

The refusals matter as much. A store that does not verify is not rewritten —
rewriting it would re-seal somebody's tamper and destroy the only evidence that
it happened. And a store that cannot be re-signed is not rewritten either.
"""

import json

from code_reviewer.application.erasure import erase, redact
from code_reviewer.domain.audit import ChainStatus
from code_reviewer.domain.provenance import DecisionRecord, RunIdentity
from code_reviewer.infrastructure.governance.sealed_sink import (
    FileAuditStore,
    SealedAuditSink,
    read_store,
    verify_store,
)
from code_reviewer.infrastructure.governance.signing import HmacSigner, NullSigner

KEY = "s3cr3t-audit-key-long-enough"
NOW = "2026-08-10T00:00:00+00:00"


def _record(merge_request="10", project="1", when="2026-01-01T00:00:00+00:00"):
    return DecisionRecord(
        verdict="pass",
        exit_code=0,
        identity=RunIdentity(package_version="2.18.0", policy_version="1.0"),
        project=project,
        merge_request=merge_request,
        recorded_at=when,
    )


def _store(tmp_path, signer=None, records=None):
    path = tmp_path / "audit.ndjson"
    sink = SealedAuditSink(path, signer=signer or NullSigner())
    for record in records or [
        _record("10", when="2025-01-01T00:00:00+00:00"),
        _record("11", when="2026-06-01T00:00:00+00:00"),
        _record("12", when="2026-07-01T00:00:00+00:00"),
    ]:
        sink.write(record)
    return path


def _payloads(path):
    return [payload for _, payload in read_store(path)]


class TestErasingByAge:
    def test_it_removes_the_records_older_than_the_cutoff(self, tmp_path):
        path = _store(tmp_path)

        outcome = erase(FileAuditStore(path), before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        assert outcome.removed == 1
        assert outcome.kept == 2

    def test_the_rewritten_store_still_verifies(self, tmp_path):
        """AC-14, and the property the whole design turns on."""
        path = _store(tmp_path)

        erase(FileAuditStore(path), before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        assert verify_store(path).status is ChainStatus.INTACT

    def test_a_removed_record_leaves_a_tombstone(self, tmp_path):
        """AC-15. Erasure and tampering must stay distinguishable, which is the
        whole reason this is not a `sed` command."""
        path = _store(tmp_path)

        erase(FileAuditStore(path), before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        tombstones = [payload for payload in _payloads(path) if "tombstone" in payload]
        assert len(tombstones) == 1

    def test_the_tombstone_names_when_and_under_which_policy(self, tmp_path):
        path = _store(tmp_path)

        erase(FileAuditStore(path), before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        tombstone = next(p["tombstone"] for p in _payloads(path) if "tombstone" in p)
        assert tombstone["removed_at"] == NOW
        assert tombstone["policy"] == "12 months"

    def test_the_tombstone_carries_nothing_from_the_record(self, tmp_path):
        path = _store(
            tmp_path, records=[_record("10", project="a-private-name", when="2020-01-01T00:00:00+00:00")]
        )

        erase(FileAuditStore(path), before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        assert "a-private-name" not in path.read_text(encoding="utf-8")

    def test_the_number_of_lines_is_unchanged(self, tmp_path):
        """A removed record leaves a marked position, not a hole."""
        path = _store(tmp_path)
        before = len(path.read_text(encoding="utf-8").splitlines())

        erase(FileAuditStore(path), before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        assert len(path.read_text(encoding="utf-8").splitlines()) == before

    def test_nothing_matching_removes_nothing(self, tmp_path):
        path = _store(tmp_path)

        outcome = erase(FileAuditStore(path), before="2000-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        assert outcome.removed == 0
        assert verify_store(path).status is ChainStatus.INTACT

    def test_a_tombstone_is_not_erased_twice(self, tmp_path):
        path = _store(tmp_path)
        erase(FileAuditStore(path), before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        outcome = erase(FileAuditStore(path), before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        assert outcome.removed == 0


class TestErasingASubject:
    def test_it_removes_the_records_of_one_merge_request(self, tmp_path):
        path = _store(tmp_path)

        outcome = erase(FileAuditStore(path), merge_request="11", policy="erasure request", now=NOW)

        assert outcome.removed == 1

    def test_it_removes_every_record_of_one_project(self, tmp_path):
        path = _store(
            tmp_path,
            records=[_record("10", project="7"), _record("11", project="7"), _record("12", project="8")],
        )

        outcome = erase(FileAuditStore(path), project="7", policy="erasure request", now=NOW)

        assert outcome.removed == 2


class TestRedaction:
    def test_it_empties_the_fields_that_name_the_subject(self, tmp_path):
        """AC-16 — the record's shape survives, so what remains is still a
        record of a review having happened."""
        path = _store(tmp_path, records=[_record("11", project="a-private-name")])

        redact(FileAuditStore(path), project="a-private-name", policy="erasure request", now=NOW)

        assert "a-private-name" not in path.read_text(encoding="utf-8")

    def test_the_record_is_still_there(self, tmp_path):
        path = _store(tmp_path, records=[_record("11", project="a-private-name")])

        redact(FileAuditStore(path), project="a-private-name", policy="erasure request", now=NOW)

        assert _payloads(path)[0]["verdict"] == "pass"

    def test_the_store_still_verifies(self, tmp_path):
        path = _store(tmp_path, records=[_record("11", project="a-private-name")])

        redact(FileAuditStore(path), project="a-private-name", policy="erasure request", now=NOW)

        assert verify_store(path).status is ChainStatus.INTACT

    def test_the_redaction_is_marked_on_the_record(self, tmp_path):
        """Otherwise an empty field is indistinguishable from one nobody set."""
        path = _store(tmp_path, records=[_record("11", project="a-private-name")])

        redact(FileAuditStore(path), project="a-private-name", policy="erasure request", now=NOW)

        assert _payloads(path)[0]["redacted_at"] == NOW

    def test_it_counts_what_it_changed(self, tmp_path):
        path = _store(tmp_path, records=[_record("10", project="7"), _record("11", project="8")])

        assert redact(FileAuditStore(path), project="7", policy="request", now=NOW).redacted == 1


class TestWhatItRefusesToDo:
    def test_a_tampered_store_is_not_rewritten(self, tmp_path):
        """Rewriting would re-seal somebody's tamper and destroy the only
        evidence that it happened."""
        path = _store(tmp_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        document = json.loads(lines[1])
        document["record"]["verdict"] = "fail"
        lines[1] = json.dumps(document, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        outcome = erase(FileAuditStore(path), merge_request="10", policy="request", now=NOW)

        assert outcome.removed == 0
        assert "verify" in outcome.refused.lower()

    def test_a_tampered_store_is_left_exactly_as_it_was(self, tmp_path):
        path = _store(tmp_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace('"pass"', '"fail"')
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        before = path.read_text(encoding="utf-8")

        erase(FileAuditStore(path), merge_request="10", policy="request", now=NOW)

        assert path.read_text(encoding="utf-8") == before

    def test_a_signed_store_is_not_rewritten_without_its_key(self, tmp_path):
        """The result would be a store nobody could verify, produced by the
        tool that exists to make stores verifiable."""
        path = _store(tmp_path, signer=HmacSigner(KEY, key_id="ops-2026"))

        outcome = erase(
            FileAuditStore(path), merge_request="10", policy="request", now=NOW, signer=NullSigner()
        )

        assert outcome.removed == 0
        assert "sign" in outcome.refused.lower()

    def test_a_signed_store_is_rewritten_with_its_key(self, tmp_path):
        signer = HmacSigner(KEY, key_id="ops-2026")
        path = _store(tmp_path, signer=signer)

        outcome = erase(FileAuditStore(path), merge_request="10", policy="request", now=NOW, signer=signer)

        assert outcome.removed == 1
        assert verify_store(path, signer).status is ChainStatus.INTACT

    def test_an_erasure_that_names_nothing_is_refused(self, tmp_path):
        """`erase everything` is a mistake somebody makes once."""
        path = _store(tmp_path)

        outcome = erase(FileAuditStore(path), policy="request", now=NOW)

        assert outcome.removed == 0
        assert outcome.refused

    def test_a_missing_store_is_refused_rather_than_created(self, tmp_path):
        outcome = erase(
            FileAuditStore(tmp_path / "absent.ndjson"), merge_request="10", policy="request", now=NOW
        )

        assert outcome.refused
        assert not (tmp_path / "absent.ndjson").exists()


class TestNothingErasesByItself:
    def test_the_review_path_does_not_import_erasure(self):
        """AC-17. No record is removed by a review, by a timer, or by a
        default — asserted by parsing rather than by a sentence."""
        import ast
        from pathlib import Path

        for module in (
            "application/review_service.py",
            "application/governance.py",
            "__main__.py",
            "serve.py",
        ):
            source = Path("code_reviewer") / module
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
                alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
            }

            assert not any("erasure" in name for name in imported), module


class TestDatingARecord:
    """Self-review S-03 and S-04 — the two ways an age policy got it wrong.

    S-03: a record with no `recorded_at` was removed by every age-based
    erasure, because `"" >= before` is false and it fell through every guard.
    The one record whose age is unknown is the one that must not go.

    S-04: timestamps were compared as strings, so `2026-06-01T05:00:00+03:00`
    (02:00Z) sorted after a 03:00Z cutoff and survived an erasure it was older
    than. Any runner outside UTC was exposed, and an erasure request that
    leaves the data in place is the failure with a legal consequence attached.
    """

    def _one(self, tmp_path, when):
        path = tmp_path / "audit.ndjson"
        SealedAuditSink(path).write(_record("1", when=when))
        return FileAuditStore(path)

    def test_an_undated_record_survives_an_age_erasure(self, tmp_path):
        store = self._one(tmp_path, "")

        outcome = erase(store, before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW)

        assert outcome.removed == 0

    def test_an_unparseable_date_survives_an_age_erasure(self, tmp_path):
        """Same rule: what cannot be dated cannot be aged out."""
        store = self._one(tmp_path, "last Tuesday")

        assert erase(store, before="2026-01-01T00:00:00+00:00", policy="12 months", now=NOW).removed == 0

    def test_an_offset_timestamp_is_compared_as_an_instant(self, tmp_path):
        """05:00+03:00 is 02:00Z, which is older than a 03:00Z cutoff."""
        store = self._one(tmp_path, "2026-06-01T05:00:00+03:00")

        outcome = erase(store, before="2026-06-01T03:00:00+00:00", policy="request", now=NOW)

        assert outcome.removed == 1

    def test_an_offset_timestamp_newer_than_the_cutoff_survives(self, tmp_path):
        store = self._one(tmp_path, "2026-06-01T05:00:00+00:00")

        assert erase(store, before="2026-06-01T03:00:00+00:00", policy="request", now=NOW).removed == 0

    def test_a_cutoff_that_cannot_be_read_erases_nothing(self, tmp_path):
        """A malformed cutoff must not delete the store."""
        store = self._one(tmp_path, "2020-01-01T00:00:00+00:00")

        outcome = erase(store, before="whenever", policy="request", now=NOW)

        assert outcome.removed == 0
        assert outcome.refused

    def test_a_naive_timestamp_is_read_as_utc(self, tmp_path):
        """The stores this project writes are UTC; a naive stamp is not a
        reason to refuse, but assuming a local zone would be."""
        store = self._one(tmp_path, "2020-01-01T00:00:00")

        assert erase(store, before="2026-01-01T00:00:00+00:00", policy="request", now=NOW).removed == 1

    def test_an_undated_record_can_still_be_erased_by_subject(self, tmp_path):
        """The date is what is unknown, not the identity."""
        store = self._one(tmp_path, "")

        assert erase(store, merge_request="1", policy="request", now=NOW).removed == 1
