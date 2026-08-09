"""Step 5 — the file, and everything about not losing what was in it."""

import json
import os
from datetime import date

import pytest

from code_reviewer.domain.recollection import Recollection, RecollectionKind
from code_reviewer.domain.severity import Severity
from code_reviewer.infrastructure.memory.json_store import SCHEMA_VERSION, JsonMemoryStore

JANUARY = date(2026, 1, 10)
MARCH = date(2026, 3, 10)


def _recollection(**overrides) -> Recollection:
    defaults = {
        "kind": RecollectionKind.FINDING,
        "file_path": "storage/repository.py",
        "rule_id": "SAST.SQL_INJECTION",
        "severity": Severity.CRITICAL,
        "first_seen": JANUARY,
        "last_seen": MARCH,
        "occurrences": 4,
        "reason": "",
    }
    return Recollection(**{**defaults, **overrides})


def _store(tmp_path) -> JsonMemoryStore:
    return JsonMemoryStore(tmp_path / ".review-memory.json")


def test_a_round_trip_preserves_every_field(tmp_path):
    store = _store(tmp_path)
    original = [
        _recollection(),
        _recollection(kind=RecollectionKind.SUPPRESSION, rule_id="SAST.WEAK_CRYPTO", reason="cache key"),
    ]

    store.save(original)

    assert store.load() == original


def test_an_absent_file_is_an_empty_memory(tmp_path):
    assert _store(tmp_path).load() == []


def test_saving_an_empty_memory_writes_a_file_rather_than_deleting_one(tmp_path):
    store = _store(tmp_path)
    store.save([_recollection()])

    store.save([])

    assert store.path.is_file()
    assert store.load() == []


def test_the_file_is_stable_across_saves_of_the_same_memory(tmp_path):
    """Sorted keys and a fixed indent, so a memory that did not change does
    not produce a diff."""
    store = _store(tmp_path)

    store.save([_recollection()])
    first = store.path.read_text(encoding="utf-8")
    store.save([_recollection()])

    assert store.path.read_text(encoding="utf-8") == first


# -- what it refuses to lose -------------------------------------------------


def test_a_corrupt_file_loads_as_empty_and_is_left_on_disk(tmp_path, caplog):
    store = _store(tmp_path)
    store.path.write_text("{ this is not json", encoding="utf-8")

    with caplog.at_level("WARNING", logger="code_reviewer.infrastructure.memory.json_store"):
        assert store.load() == []

    assert store.path.is_file(), "a tool that deletes state it does not understand is not trusted with state"
    assert "could not be read" in caplog.text


def test_a_file_that_is_not_an_object_loads_as_empty(tmp_path):
    store = _store(tmp_path)
    store.path.write_text("[1, 2, 3]", encoding="utf-8")

    assert store.load() == []


def test_a_future_schema_version_loads_as_empty_rather_than_half_read(tmp_path, caplog):
    store = _store(tmp_path)
    store.path.write_text(
        json.dumps({"version": SCHEMA_VERSION + 1, "recollections": [{"anything": True}]}),
        encoding="utf-8",
    )

    with caplog.at_level("WARNING", logger="code_reviewer.infrastructure.memory.json_store"):
        assert store.load() == []

    assert "version" in caplog.text


def test_a_missing_recollections_list_loads_as_empty(tmp_path):
    store = _store(tmp_path)
    store.path.write_text(json.dumps({"version": SCHEMA_VERSION}), encoding="utf-8")

    assert store.load() == []


def test_one_unreadable_entry_does_not_cost_the_others(tmp_path):
    """The file is written by this program, so a bad entry means a hand edit
    or another version. Losing one line of history beats losing all of it."""
    store = _store(tmp_path)
    store.save([_recollection()])

    document = json.loads(store.path.read_text(encoding="utf-8"))
    document["recollections"].insert(0, {"kind": "finding", "rule_id": "A.B"})
    document["recollections"].append({"kind": "not-a-kind", "file_path": "a", "rule_id": "b"})
    store.path.write_text(json.dumps(document), encoding="utf-8")

    assert [item.rule_id for item in store.load()] == ["SAST.SQL_INJECTION"]


def test_an_entry_with_an_impossible_date_range_is_skipped(tmp_path):
    store = _store(tmp_path)
    store.save([_recollection()])

    document = json.loads(store.path.read_text(encoding="utf-8"))
    document["recollections"][0]["last_seen"] = "2020-01-01"
    store.path.write_text(json.dumps(document), encoding="utf-8")

    assert store.load() == []


# -- atomicity ---------------------------------------------------------------


def test_a_failed_write_leaves_the_previous_file_untouched(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save([_recollection()])
    before = store.path.read_bytes()

    def refuse(*_args, **_kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "replace", refuse)

    with pytest.raises(OSError):
        store.save([_recollection(occurrences=99)])

    assert store.path.read_bytes() == before


def test_a_failed_write_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError("nope")))

    with pytest.raises(OSError):
        store.save([_recollection()])

    assert list(tmp_path.iterdir()) == []


def test_a_successful_write_leaves_no_temporary_file_behind(tmp_path):
    store = _store(tmp_path)

    store.save([_recollection()])

    assert [path.name for path in tmp_path.iterdir()] == [".review-memory.json"]


def test_the_parent_directory_is_created(tmp_path):
    store = JsonMemoryStore(tmp_path / "state" / "memory.json")

    store.save([_recollection()])

    assert store.load() == [_recollection()]
