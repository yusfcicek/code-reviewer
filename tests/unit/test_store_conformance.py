"""Step 4 — what a store must do, since this repository will not choose one.

Level 24 refused to pick a database, an object store or a managed service, and
the reason still holds: the sink is a port, and a format any store can hold is
worth more than a binding to one vendor's client.

What was missing is that *"any store can hold it"* was an assertion. Nothing
said what a store has to **do**, so an adapter written by somebody else had no
way to find out whether it qualified, and this repository had no way to find out
whether its own still did.

So the refusal keeps its reason and gains a contract. Every `AuditStore` adapter
runs this suite. The shipped file adapter passes it; two adapters written to be
wrong fail it, because a conformance suite nothing fails is the defect
self-review 27 was about — and it is the cheapest one to reintroduce here, where
the only adapter is the one that already worked.
"""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import pytest

from code_reviewer.application.ports import AuditStore, Signer
from code_reviewer.domain.audit import GENESIS, sealed
from code_reviewer.domain.provenance import DecisionRecord, RunIdentity
from code_reviewer.infrastructure.governance.sealed_sink import FileAuditStore, SealedAuditSink
from code_reviewer.infrastructure.governance.signing import HmacSigner

KEY = "conformance-key-material-long-enough"


def _record(merge_request: str) -> DecisionRecord:
    return DecisionRecord(
        verdict="pass",
        exit_code=0,
        identity=RunIdentity(package_version="2.24.0", policy_version="1.0"),
        project="1",
        merge_request=merge_request,
    )


def _file_store(tmp_path, count: int, signer: Signer | None = None) -> AuditStore:
    path = tmp_path / "audit.ndjson"
    sink = SealedAuditSink(path, signer=signer)
    for index in range(count):
        sink.write(_record(str(index)))
    return FileAuditStore(path)


class _InMemoryStore(AuditStore):
    """The smallest adapter that could be correct. The baseline for the two below."""

    def __init__(self, payloads: Sequence[Mapping[str, Any]] = (), signer: Signer | None = None):
        self._payloads = [dict(payload) for payload in payloads]
        self._signer = signer
        self._present = True

    def exists(self) -> bool:
        return self._present

    def payloads(self) -> list[dict]:
        return [dict(payload) for payload in self._payloads]

    def is_signed(self) -> bool:
        return self._signer is not None and self._signer.is_signing

    def is_verifiable(self, signer: Signer) -> tuple[bool, str]:
        return True, ""

    def replace(self, payloads: "Sequence[Mapping[str, Any]]", signer: Signer) -> None:
        self._payloads = [dict(payload) for payload in payloads]


class _ReorderingStore(_InMemoryStore):
    """Reads back in a different order. What a store keyed by a hash gives you."""

    def payloads(self) -> list[dict]:
        return list(reversed(super().payloads()))


class _LosingStore(_InMemoryStore):
    """Drops the most recent write. What an eventually-consistent read gives you."""

    def payloads(self) -> list[dict]:
        return super().payloads()[:-1]


def _conforms(store: AuditStore, written: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every way this store fails the contract, in reading order.

    A list rather than an assertion so the suite can be run against an adapter
    that fails and say all of what is wrong with it.
    """
    complaints = []
    read = store.payloads()

    if len(read) != len(written):
        complaints.append(f"holds {len(read)} record(s); {len(written)} were written")
    if [payload.get("merge_request") for payload in read] != [
        payload.get("merge_request") for payload in written
    ]:
        complaints.append("reads back in an order other than the one it was written in")
    if not store.exists():
        complaints.append("says it does not exist after being written to")
    return complaints


class TestTheShippedAdapter:
    """AC-9. The file adapter answers the contract it has always answered."""

    def test_it_reads_back_everything_it_was_given_in_order(self, tmp_path):
        store = _file_store(tmp_path, count=5)
        written = [_record(str(index)) for index in range(5)]

        assert _conforms(store, [{"merge_request": r.merge_request} for r in written]) == []

    def test_an_absent_store_is_not_an_empty_one(self, tmp_path):
        """A store with no records is a deployment that reviewed nothing; a
        store that is not there is a path somebody got wrong. An erasure
        refuses the second rather than creating it."""
        assert not FileAuditStore(tmp_path / "nowhere.ndjson").exists()

    def test_an_empty_store_exists_and_holds_nothing(self, tmp_path):
        path = tmp_path / "audit.ndjson"
        path.write_text("", encoding="utf-8")
        store = FileAuditStore(path)

        assert store.exists()
        assert store.payloads() == []

    def test_it_reports_whether_anything_is_signed(self, tmp_path):
        assert not _file_store(tmp_path, count=1).is_signed()
        assert _file_store(tmp_path, count=1, signer=HmacSigner(KEY, key_id="k")).is_signed()

    def test_a_replacement_is_readable_and_still_sealed(self, tmp_path):
        store = _file_store(tmp_path, count=3, signer=HmacSigner(KEY, key_id="k"))

        store.replace([{"verdict": "pass", "merge_request": "kept"}], HmacSigner(KEY, key_id="k"))

        assert [payload["merge_request"] for payload in store.payloads()] == ["kept"]
        assert store.is_verifiable(HmacSigner(KEY, key_id="k"))[0]

    def test_a_replacement_under_a_key_it_cannot_check_is_not_claimed_verified(self, tmp_path):
        """Level 30. The store is re-sealed under the current key; a verifier
        holding a different one must not be told the result verifies."""
        store = _file_store(tmp_path, count=2, signer=HmacSigner(KEY, key_id="k"))
        store.replace([{"verdict": "pass", "merge_request": "kept"}], HmacSigner(KEY, key_id="k"))

        verified, reason = store.is_verifiable(HmacSigner("another-key-long-enough", key_id="other"))

        assert not verified
        assert reason


class TestAnAdapterThatIsWrong:
    """AC-10. A conformance suite nothing fails proves nothing about the one
    thing it is run on, and here that thing is the adapter that already worked.
    """

    WRITTEN: ClassVar[list[dict[str, str]]] = [
        {"merge_request": "0"},
        {"merge_request": "1"},
        {"merge_request": "2"},
    ]

    def test_the_baseline_in_memory_adapter_conforms(self):
        assert _conforms(_InMemoryStore(self.WRITTEN), self.WRITTEN) == []

    def test_one_that_reorders_is_caught(self):
        complaints = _conforms(_ReorderingStore(self.WRITTEN), self.WRITTEN)

        assert any("order" in complaint for complaint in complaints)

    def test_one_that_loses_the_last_write_is_caught(self):
        complaints = _conforms(_LosingStore(self.WRITTEN), self.WRITTEN)

        assert any("record(s)" in complaint for complaint in complaints)


class TestWhatTheContractRestsOn:
    """The two properties the format needs from whatever holds it, asserted
    against the domain rather than against an adapter — an adapter that cannot
    give them makes the chain meaningless rather than merely slow."""

    def test_order_is_what_the_chain_is_made_of(self):
        """Read two records back in the wrong order and the links do not hold.
        That is why ordering is a contract and not a preference."""
        from code_reviewer.domain.audit import ChainStatus, verify

        entries, previous = [], GENESIS
        for sequence, payload in enumerate([{"a": 1}, {"a": 2}], start=1):
            seal = sealed(payload, previous, None, sequence)
            entries.append((seal, payload))
            previous = seal.digest

        assert verify(entries).status is not ChainStatus.TAMPERED
        assert verify(list(reversed(entries))).status is ChainStatus.TAMPERED

    def test_a_lost_record_is_only_visible_against_an_anchor_from_outside(self):
        """The honest half. A store that silently drops its most recent write
        produces a valid chain, and no adapter can be tested out of that — a
        prefix of a valid chain is a valid chain (self-review 24, S-01). The
        contract is therefore that a store reports its own end, and an operator
        compares it against a counter kept elsewhere."""
        from code_reviewer.domain.audit import ChainStatus, verify

        entries, previous = [], GENESIS
        for sequence, payload in enumerate([{"a": 1}, {"a": 2}], start=1):
            seal = sealed(payload, previous, None, sequence)
            entries.append((seal, payload))
            previous = seal.digest

        truncated = entries[:1]

        assert verify(truncated).status is not ChainStatus.TAMPERED
        assert verify(truncated, expect_at_least=2).status is ChainStatus.TAMPERED


@pytest.mark.parametrize("method", ["exists", "payloads", "is_signed", "is_verifiable", "replace"])
def test_the_port_names_every_method_an_adapter_must_write(method):
    """The contract as a list somebody implementing it can read. A method added
    to the port without a line here is a method no adapter knows it owes."""
    assert method in AuditStore.__abstractmethods__
