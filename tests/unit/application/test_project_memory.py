"""Step 4 — the use case: recall before, observe during, persist after."""

from datetime import date, timedelta

from code_reviewer.application.ports import MemoryStore
from code_reviewer.application.project_memory import ProjectMemory
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.recollection import Recollection, RecollectionKind
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import SuppressedFinding, SuppressionDirective

TODAY = date(2026, 8, 9)


def _clock():
    return TODAY


def _finding(rule_id="SAST.SQL_INJECTION", path="storage/repository.py", **overrides) -> Finding:
    defaults = {
        "category": FindingCategory.SECURITY,
        "severity": Severity.CRITICAL,
        "file_path": path,
        "line_number": 12,
        "title": "SQL Injection",
        "description": "A query is built from a request parameter called secret_token",
        "remediation": "Use a parameterised query",
        "rule_id": rule_id,
        "evidence": "query = 'SELECT * FROM users WHERE id = ' + AKIAIOSFODNN7EXAMPLE",
    }
    return Finding(**{**defaults, **overrides})


def _recollection(**overrides) -> Recollection:
    defaults = {
        "kind": RecollectionKind.FINDING,
        "file_path": "storage/repository.py",
        "rule_id": "SAST.SQL_INJECTION",
        "severity": Severity.CRITICAL,
        "first_seen": TODAY - timedelta(days=40),
        "last_seen": TODAY - timedelta(days=10),
        "occurrences": 4,
    }
    return Recollection(**{**defaults, **overrides})


class StubStore(MemoryStore):
    def __init__(self, stored=(), load_error=None, save_error=None):
        self.stored = list(stored)
        self.load_error = load_error
        self.save_error = save_error
        self.loads = 0
        self.saved: list[Recollection] | None = None

    def load(self):
        self.loads += 1
        if self.load_error is not None:
            raise self.load_error
        return list(self.stored)

    def save(self, recollections):
        if self.save_error is not None:
            raise self.save_error
        self.saved = list(recollections)


def _memory(store=None, **overrides) -> ProjectMemory:
    return ProjectMemory(store or StubStore(), clock=_clock, **overrides)


# -- recall ------------------------------------------------------------------


def test_what_was_known_before_the_run_is_recalled():
    memory = _memory(StubStore([_recollection()]))

    recalled = memory.recall("storage/repository.py")

    assert [item.rule_id for item in recalled] == ["SAST.SQL_INJECTION"]


def test_the_store_is_read_once_however_many_files_are_reviewed():
    store = StubStore([_recollection()])
    memory = _memory(store)

    memory.recall("storage/repository.py")
    memory.recall("storage/migrations.py")
    memory.recurrence_of(_finding())

    assert store.loads == 1


def test_a_finding_seen_before_is_recurring():
    memory = _memory(StubStore([_recollection()]))

    recurrence = memory.recurrence_of(_finding())

    assert recurrence is not None
    assert recurrence.occurrences == 4


def test_a_finding_never_seen_before_is_not_recurring():
    memory = _memory(StubStore([_recollection()]))

    assert memory.recurrence_of(_finding(rule_id="SAST.WEAK_CRYPTO")) is None


def test_a_finding_with_no_rule_id_is_never_recurring():
    assert _memory(StubStore([_recollection()])).recurrence_of(_finding(rule_id="")) is None


def test_a_suppression_of_the_same_rule_does_not_make_a_finding_recurring():
    """One is 'this keeps happening', the other is 'somebody decided'."""
    suppression = _recollection(kind=RecollectionKind.SUPPRESSION)

    assert _memory(StubStore([suppression])).recurrence_of(_finding()) is None


def test_this_runs_own_observations_do_not_make_a_finding_recurring():
    """A finding reported for the first time this morning is not recurring,
    and a memory that counted the sighting it is describing would say it was."""
    memory = _memory(StubStore())
    memory.observe_findings([_finding()])

    assert memory.recurrence_of(_finding()) is None


# -- observing ---------------------------------------------------------------


def test_findings_become_recollections():
    memory = _memory()

    memory.observe_findings([_finding(), _finding(rule_id="SAST.WEAK_CRYPTO")])

    assert [item.rule_id for item in memory.observed] == ["SAST.SQL_INJECTION", "SAST.WEAK_CRYPTO"]
    assert all(item.kind is RecollectionKind.FINDING for item in memory.observed)
    assert all(item.first_seen == TODAY and item.last_seen == TODAY for item in memory.observed)


def test_a_finding_with_no_rule_id_is_not_remembered():
    """Identity is what makes a memory a memory rather than a list."""
    memory = _memory()

    memory.observe_findings([_finding(rule_id="")])

    assert memory.observed == ()


def test_a_finding_with_no_file_path_is_not_remembered():
    memory = _memory()

    memory.observe_findings([_finding(path="")])

    assert memory.observed == ()


def test_nothing_a_contributor_wrote_is_remembered():
    """AC-13. The finding carries an evidence line containing a credential-
    shaped string and a description quoting the diff. Neither may survive:
    a memory file that accumulates contributor text is a stored injection with
    a long half-life, and a credential store nobody declared."""
    store = StubStore()
    memory = _memory(store)

    memory.observe_findings([_finding()])
    memory.persist()

    written = repr(store.saved)
    assert "AKIAIOSFODNN7EXAMPLE" not in written
    assert "secret_token" not in written
    assert "Use a parameterised query" not in written


def test_a_suppression_is_remembered_with_its_reason():
    memory = _memory()
    directive = SuppressionDirective(rule_id="SAST.WEAK_CRYPTO", reason="md5 is a cache key here", line=4)

    memory.observe_suppressions("cache/keys.py", [SuppressedFinding(finding=_finding(), directive=directive)])

    remembered = memory.observed[0]
    assert remembered.kind is RecollectionKind.SUPPRESSION
    assert remembered.file_path == "cache/keys.py"
    assert remembered.rule_id == "SAST.WEAK_CRYPTO"
    assert remembered.reason == "md5 is a cache key here"


def test_a_suppression_with_no_rule_is_not_remembered():
    memory = _memory()
    directive = SuppressionDirective(rule_id="", reason="whatever", line=4)

    memory.observe_suppressions("a.py", [SuppressedFinding(finding=_finding(), directive=directive)])

    assert memory.observed == ()


# -- persisting --------------------------------------------------------------


def test_persisting_consolidates_with_what_was_known():
    store = StubStore([_recollection()])
    memory = _memory(store)

    memory.observe_findings([_finding()])
    memory.persist()

    assert store.saved is not None
    assert len(store.saved) == 1
    assert store.saved[0].occurrences == 5
    assert store.saved[0].last_seen == TODAY


def test_persisting_forgets_what_has_decayed_past_the_floor():
    ancient = _recollection(
        rule_id="A.ANCIENT",
        severity=Severity.INFO,
        occurrences=1,
        first_seen=TODAY - timedelta(days=400),
        last_seen=TODAY - timedelta(days=400),
    )
    store = StubStore([ancient])
    memory = _memory(store)

    memory.observe_findings([_finding()])
    memory.persist()

    assert [item.rule_id for item in store.saved] == ["SAST.SQL_INJECTION"]


def test_persisting_respects_the_capacity():
    store = StubStore()
    memory = _memory(store, capacity=2)

    memory.observe_findings([_finding(rule_id=f"A.RULE{index}") for index in range(6)])
    memory.persist()

    assert len(store.saved) == 2


def test_a_run_that_read_nothing_and_saw_nothing_does_not_rewrite_the_file():
    store = StubStore()

    _memory(store).persist()

    assert store.saved is None


# -- failure -----------------------------------------------------------------


def test_a_store_that_cannot_be_read_recalls_nothing():
    memory = _memory(StubStore(load_error=OSError("permission denied")))

    assert memory.recall("storage/repository.py") == []
    assert memory.recurrence_of(_finding()) is None


def test_a_failed_read_is_logged(caplog):
    memory = _memory(StubStore(load_error=OSError("permission denied")))

    with caplog.at_level("WARNING", logger="code_reviewer.application.project_memory"):
        memory.recall("a.py")

    assert "Could not read the project memory" in caplog.text


def test_a_store_that_cannot_be_written_does_not_raise(caplog):
    memory = _memory(StubStore(save_error=OSError("read-only file system")))
    memory.observe_findings([_finding()])

    with caplog.at_level("WARNING", logger="code_reviewer.application.project_memory"):
        memory.persist()

    assert "Could not write the project memory" in caplog.text


def test_a_broken_store_still_lets_the_run_observe_and_persist():
    memory = _memory(StubStore(load_error=OSError("gone"), save_error=OSError("gone")))

    memory.observe_findings([_finding()])
    memory.persist()

    assert len(memory.observed) == 1
