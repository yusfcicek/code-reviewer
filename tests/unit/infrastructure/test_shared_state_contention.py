"""Step 4 — the unglamorous half.

Two locks, and two tests that run eight threads at an object and check the
*result* rather than the absence of a crash. "It has a lock" is not evidence
that the lock is around the right thing (decision D-6).
"""

import threading

from code_reviewer.infrastructure.memory.smart_memory import SmartMemoryStrategy
from code_reviewer.infrastructure.tools.workspace import OutsideWorkspaceError, Workspace

THREADS = 8


def _run(target, count: int = THREADS) -> None:
    workers = [threading.Thread(target=target) for _ in range(count)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()


class _Provider:
    """A memory strategy needs a provider; nothing here calls a model."""

    def get_chat_model(self):
        return None


# -- the read budget ---------------------------------------------------------


def test_the_read_budget_is_spent_exactly_once_per_read(tmp_path):
    """Without the lock, two reads that each fit under the ceiling can both
    pass the check and then both spend — which is how a budget is exceeded by
    a whole file."""
    payload = "x" * 1000
    for index in range(THREADS * 4):
        (tmp_path / f"file{index}.py").write_text(payload, encoding="utf-8")

    workspace = Workspace(tmp_path, total_read_budget_bytes=10_000_000)
    counter = iter(range(THREADS * 4))
    lock = threading.Lock()

    def read_four():
        for _ in range(4):
            with lock:
                index = next(counter)
            workspace.read(f"file{index}.py")

    _run(read_four)

    allowed = [record for record in workspace.audit_log if record.allowed]
    assert workspace.bytes_read == sum(record.size for record in allowed)
    assert workspace.bytes_read == len(allowed) * 1000


def test_the_budget_stops_exactly_at_its_ceiling_under_contention(tmp_path):
    payload = "x" * 1000
    for index in range(40):
        (tmp_path / f"file{index}.py").write_text(payload, encoding="utf-8")

    # Room for exactly ten files.
    workspace = Workspace(tmp_path, total_read_budget_bytes=10_000)
    counter = iter(range(40))
    lock = threading.Lock()
    refusals = []

    def read_five():
        for _ in range(5):
            with lock:
                index = next(counter)
            try:
                workspace.read(f"file{index}.py")
            except OutsideWorkspaceError:
                refusals.append(index)

    _run(read_five)

    assert workspace.bytes_read <= 10_000
    assert workspace.bytes_read == 10_000, "the budget should be spent right up to its ceiling"
    assert len(refusals) == 30


def test_every_read_is_audited_exactly_once(tmp_path):
    for index in range(THREADS):
        (tmp_path / f"file{index}.py").write_text("x" * 100, encoding="utf-8")

    workspace = Workspace(tmp_path, total_read_budget_bytes=10_000_000)
    counter = iter(range(THREADS))
    lock = threading.Lock()

    def read_one():
        with lock:
            index = next(counter)
        workspace.read(f"file{index}.py")

    _run(read_one)

    allowed = [record for record in workspace.audit_log if record.allowed]
    assert len(allowed) == THREADS
    assert len({record.path for record in allowed}) == THREADS


# -- the memory --------------------------------------------------------------


def test_no_insight_is_lost_under_contention():
    """One strategy is shared by the whole committee. Appends to a list are
    atomic; "is it already in the list, and if not append and recount" is
    not."""
    memory = SmartMemoryStrategy(_Provider())
    per_thread = 25
    counter = iter(range(THREADS * per_thread))
    lock = threading.Lock()

    def log_many():
        for _ in range(per_thread):
            with lock:
                index = next(counter)
            memory.log_insight(f"[SECURITY] finding number {index}")

    _run(log_many)

    stored = {insight.content for insight in memory.critical_insights}
    assert len(stored) == THREADS * per_thread


def test_insights_of_every_priority_survive_contention():
    memory = SmartMemoryStrategy(_Provider())
    categories = ["SECURITY", "BREAKING", "PERFORMANCE", "GENERAL"]
    counter = iter(range(THREADS * 20))
    lock = threading.Lock()

    def log_many():
        for _ in range(20):
            with lock:
                index = next(counter)
            memory.log_insight(f"[{categories[index % len(categories)]}] item {index}")

    _run(log_many)

    total = sum(
        len(bucket)
        for bucket in (
            memory.critical_insights,
            memory.high_insights,
            memory.normal_insights,
            memory.low_insights,
        )
    )
    assert total == THREADS * 20


def test_a_duplicate_insight_is_still_stored_once_under_contention():
    """The membership test and the append are one decision, and two threads
    passing the test at the same time would store it twice."""
    memory = SmartMemoryStrategy(_Provider())

    def log_the_same():
        for _ in range(20):
            memory.log_insight("[SECURITY] the same finding")

    _run(log_the_same)

    assert len(memory.critical_insights) == 1
