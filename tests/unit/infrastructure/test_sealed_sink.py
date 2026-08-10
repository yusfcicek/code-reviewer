"""Step 4 — a sink that seals what it writes.

The part worth testing hardest is the read: the previous digest comes from the
**file**, not from memory, so a process restart continues the chain instead of
starting a second one beside it. A sink that kept the digest in an attribute
would produce a store that verifies inside one process and forks at every
deployment.
"""

import json
import logging

from code_reviewer.domain.audit import GENESIS, ChainStatus
from code_reviewer.domain.provenance import RunIdentity
from code_reviewer.infrastructure.governance.sealed_sink import SealedAuditSink, read_store, verify_store
from code_reviewer.infrastructure.governance.signing import HmacSigner, NullSigner

KEY = "s3cr3t-audit-key-long-enough"


def _record(verdict="pass", merge_request="10"):
    from code_reviewer.domain.provenance import DecisionRecord

    return DecisionRecord(
        verdict=verdict,
        exit_code=0,
        identity=RunIdentity(package_version="2.18.0", policy_version="1.0"),
        project="1",
        merge_request=merge_request,
    )


def _sink(tmp_path, signer=None):
    return SealedAuditSink(tmp_path / "audit.ndjson", signer=signer or NullSigner())


def _lines(tmp_path):
    return (tmp_path / "audit.ndjson").read_text(encoding="utf-8").splitlines()


class TestWhatIsWritten:
    def test_a_record_is_written_as_one_line(self, tmp_path):
        _sink(tmp_path).write(_record())

        assert len(_lines(tmp_path)) == 1

    def test_the_line_carries_the_record_and_its_seal(self, tmp_path):
        _sink(tmp_path).write(_record())

        document = json.loads(_lines(tmp_path)[0])

        assert document["record"]["verdict"] == "pass"
        assert document["seal"]["digest"]

    def test_the_first_record_names_the_genesis_value(self, tmp_path):
        _sink(tmp_path).write(_record())

        assert json.loads(_lines(tmp_path)[0])["seal"]["previous"] == GENESIS

    def test_the_second_record_names_the_first(self, tmp_path):
        sink = _sink(tmp_path)
        sink.write(_record(merge_request="10"))
        sink.write(_record(merge_request="11"))

        first, second = (json.loads(line) for line in _lines(tmp_path))

        assert second["seal"]["previous"] == first["seal"]["digest"]

    def test_an_unsigned_store_carries_no_signature_field_content(self, tmp_path):
        _sink(tmp_path).write(_record())

        seal = json.loads(_lines(tmp_path)[0])["seal"]

        assert seal["signature"] == ""
        assert seal["key_id"] == ""


class TestSigning:
    def test_a_signed_record_carries_a_signature_and_a_key_id(self, tmp_path):
        _sink(tmp_path, HmacSigner(KEY, key_id="ops-2026")).write(_record())

        seal = json.loads(_lines(tmp_path)[0])["seal"]

        assert seal["signature"]
        assert seal["key_id"] == "ops-2026"

    def test_the_key_is_never_in_the_store(self, tmp_path):
        _sink(tmp_path, HmacSigner(KEY, key_id="ops-2026")).write(_record())

        assert KEY not in (tmp_path / "audit.ndjson").read_text(encoding="utf-8")

    def test_a_signer_that_raises_costs_the_signature_not_the_record(self, tmp_path, caplog):
        """AC-3. An accountability feature may not lose the thing it accounts for."""

        class _Broken(NullSigner):
            @property
            def is_signing(self):
                return True

            def sign(self, digest):
                raise RuntimeError("the HSM is unreachable")

        with caplog.at_level(logging.WARNING):
            _sink(tmp_path, _Broken()).write(_record())

        assert json.loads(_lines(tmp_path)[0])["seal"]["signature"] == ""
        assert "unsigned" in caplog.text.lower()


class TestTheChainSurvivesTheProcess:
    def test_a_new_sink_continues_the_existing_chain(self, tmp_path):
        """The digest comes from the file. A sink that kept it in an attribute
        would fork the chain at every restart."""
        _sink(tmp_path).write(_record(merge_request="10"))
        _sink(tmp_path).write(_record(merge_request="11"))

        first, second = (json.loads(line) for line in _lines(tmp_path))

        assert second["seal"]["previous"] == first["seal"]["digest"]

    def test_a_store_that_ends_in_a_partial_line_is_not_chained_onto_blindly(self, tmp_path, caplog):
        path = tmp_path / "audit.ndjson"
        _sink(tmp_path).write(_record())
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"record": {"verdict": "pa')

        with caplog.at_level(logging.WARNING):
            _sink(tmp_path).write(_record(merge_request="11"))

        assert "chain" in caplog.text.lower()

    def test_a_missing_store_starts_at_genesis(self, tmp_path):
        _sink(tmp_path).write(_record())

        assert json.loads(_lines(tmp_path)[0])["seal"]["previous"] == GENESIS

    def test_an_unwritable_path_costs_the_record_and_not_the_review(self, tmp_path, caplog):
        sink = SealedAuditSink(tmp_path / "nope" / "x" / "audit.ndjson", signer=NullSigner())
        (tmp_path / "nope").write_text("not a directory")

        with caplog.at_level(logging.WARNING):
            sink.write(_record())

        assert "record" in caplog.text.lower()


class TestReadingAndVerifying:
    def test_a_written_store_verifies_intact(self, tmp_path):
        sink = _sink(tmp_path)
        for index in range(5):
            sink.write(_record(merge_request=str(index)))

        assert verify_store(tmp_path / "audit.ndjson").status is ChainStatus.INTACT

    def test_a_signed_store_verifies_with_its_key(self, tmp_path):
        signer = HmacSigner(KEY, key_id="ops-2026")
        sink = _sink(tmp_path, signer)
        sink.write(_record())
        sink.write(_record(merge_request="11"))

        verdict = verify_store(tmp_path / "audit.ndjson", signer)

        assert verdict.status is ChainStatus.INTACT
        assert verdict.signed == 2

    def test_an_edited_record_is_caught(self, tmp_path):
        sink = _sink(tmp_path)
        sink.write(_record(verdict="fail_placeholder"))
        sink.write(_record(merge_request="11"))

        path = tmp_path / "audit.ndjson"
        lines = path.read_text(encoding="utf-8").splitlines()
        document = json.loads(lines[0])
        document["record"]["verdict"] = "pass"
        lines[0] = json.dumps(document, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        verdict = verify_store(path)

        assert verdict.status is ChainStatus.TAMPERED
        assert verdict.position == 1

    def test_a_deleted_line_is_caught(self, tmp_path):
        sink = _sink(tmp_path)
        for index in range(3):
            sink.write(_record(merge_request=str(index)))

        path = tmp_path / "audit.ndjson"
        lines = path.read_text(encoding="utf-8").splitlines()
        del lines[1]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        assert verify_store(path).status is ChainStatus.TAMPERED

    def test_a_missing_store_reads_as_nothing_rather_than_raising(self, tmp_path):
        assert read_store(tmp_path / "absent.ndjson") == []

    def test_a_malformed_line_is_reported_as_unreadable(self, tmp_path):
        path = tmp_path / "audit.ndjson"
        path.write_text("not json at all\n", encoding="utf-8")

        verdict = verify_store(path)

        assert verdict.status is ChainStatus.TAMPERED
        assert verdict.position == 1

    def test_a_thousand_records_verify(self, tmp_path):
        """AC-10, and the shape of the cost: reading is linear, and so is
        verifying. A verifier nobody can afford to run is a verifier nobody runs."""
        sink = _sink(tmp_path)
        for index in range(1000):
            sink.write(_record(merge_request=str(index)))

        verdict = verify_store(tmp_path / "audit.ndjson")

        assert verdict.status is ChainStatus.INTACT
        assert verdict.checked == 1000
