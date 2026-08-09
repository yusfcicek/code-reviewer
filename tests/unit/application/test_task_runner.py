"""Steps 1 and 2 — what running a group of tasks means, both ways."""

import threading
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from code_reviewer.application.tasks import SequentialRunner, TaskOutcome, TaskRunner
from code_reviewer.infrastructure.concurrency.thread_pool import ThreadPoolRunner

RUNNERS = [
    pytest.param(SequentialRunner(), id="sequential"),
    pytest.param(ThreadPoolRunner(max_workers=4), id="pool"),
]


# -- the outcome -------------------------------------------------------------


def test_a_successful_outcome_carries_its_value():
    outcome = TaskOutcome.ok("done", duration_ms=12)

    assert outcome.succeeded
    assert outcome.value == "done"
    assert outcome.duration_ms == 12


def test_reading_a_value_off_a_failed_outcome_is_refused():
    """`None` is a value a task may legitimately return, and a reader who
    cannot tell the two apart will eventually write the bug that says they
    are the same."""
    outcome = TaskOutcome.failed("RuntimeError: no")

    with pytest.raises(ValueError):
        _ = outcome.value


def test_a_task_that_returns_none_is_still_a_success():
    assert TaskOutcome.ok(None).succeeded
    assert TaskOutcome.ok(None).value is None


def test_a_timed_out_outcome_says_so_and_names_the_bound():
    outcome = TaskOutcome.timeout(2.5)

    assert outcome.timed_out
    assert not outcome.succeeded
    assert "2.5s" in outcome.error_type


# -- both runners ------------------------------------------------------------


@pytest.mark.parametrize("runner", RUNNERS)
def test_outcomes_come_back_in_the_order_the_tasks_were_given(runner: TaskRunner):
    def slow(value):
        def task():
            time.sleep(0.02 if value == "first" else 0.0)
            return value

        return task

    outcomes = runner.run_all([slow("first"), slow("second"), slow("third")])

    assert [outcome.value for outcome in outcomes] == ["first", "second", "third"]


@pytest.mark.parametrize("runner", RUNNERS)
def test_a_failing_task_does_not_affect_the_others(runner: TaskRunner):
    def explode():
        raise RuntimeError("the endpoint refused")

    outcomes = runner.run_all([lambda: "a", explode, lambda: "c"])

    assert outcomes[0].value == "a"
    assert not outcomes[1].succeeded
    assert "RuntimeError" in outcomes[1].error_type
    assert outcomes[2].value == "c"


@pytest.mark.parametrize("runner", RUNNERS)
def test_running_nothing_returns_nothing(runner: TaskRunner):
    assert runner.run_all([]) == []


@pytest.mark.parametrize("runner", RUNNERS)
def test_a_single_task_works(runner: TaskRunner):
    assert [outcome.value for outcome in runner.run_all([lambda: 1])] == [1]


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.integers(0, 20), min_size=0, max_size=6))
def test_the_two_runners_agree(values):
    """AC-5. The pool is only worth having if it changes nothing but the
    wall clock."""

    def make(value):
        return lambda: value * 2

    tasks = [make(value) for value in values]

    sequential = SequentialRunner().run_all(tasks)
    pooled = ThreadPoolRunner(max_workers=3).run_all(tasks)

    assert [outcome.value for outcome in sequential] == [outcome.value for outcome in pooled]


# -- the pool ----------------------------------------------------------------


def test_the_pool_actually_overlaps_the_waiting():
    """The assertion that says this level does anything at all."""

    def sleeper():
        time.sleep(0.1)
        return "done"

    started = time.monotonic()
    outcomes = ThreadPoolRunner(max_workers=4).run_all([sleeper for _ in range(4)])
    elapsed = time.monotonic() - started

    assert all(outcome.succeeded for outcome in outcomes)
    assert elapsed < 0.3, f"four 100 ms sleeps took {elapsed:.2f}s"


def test_max_workers_bounds_how_many_run_at_once():
    peak = 0
    running = 0
    lock = threading.Lock()

    def watched():
        nonlocal peak, running
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return None

    ThreadPoolRunner(max_workers=2).run_all([watched for _ in range(6)])

    assert peak <= 2


def test_a_hung_task_times_out_and_the_others_still_return():
    def hang():
        time.sleep(5)
        return "never"

    started = time.monotonic()
    outcomes = ThreadPoolRunner(max_workers=3).run_all([lambda: "a", hang, lambda: "c"], timeout_s=0.15)
    elapsed = time.monotonic() - started

    assert outcomes[0].value == "a"
    assert outcomes[1].timed_out
    assert outcomes[2].value == "c"
    assert elapsed < 1.0, f"one hung task cost the group {elapsed:.2f}s"


def test_several_hung_tasks_cost_one_timeout_between_them():
    """The deadline is the group's, not each task's, so ten hung tasks cost
    one timeout rather than ten."""

    def hang():
        time.sleep(5)

    started = time.monotonic()
    outcomes = ThreadPoolRunner(max_workers=4).run_all([hang for _ in range(4)], timeout_s=0.15)

    assert all(outcome.timed_out for outcome in outcomes)
    assert time.monotonic() - started < 1.0


def test_a_pool_that_abandoned_a_task_is_tainted_and_replaced():
    """Python cannot kill a thread. The hung worker is still in there holding
    whatever it was holding, so the pool is not reused (decision D-3)."""
    runner = ThreadPoolRunner(max_workers=2)

    runner.run_all([lambda: time.sleep(5)], timeout_s=0.05)
    assert runner.is_tainted

    outcomes = runner.run_all([lambda: "fresh"])

    assert outcomes[0].value == "fresh"
    assert not runner.is_tainted
    runner.shutdown()


def test_a_pool_of_one_still_orders_its_outcomes():
    outcomes = ThreadPoolRunner(max_workers=1).run_all([lambda: 1, lambda: 2, lambda: 3])

    assert [outcome.value for outcome in outcomes] == [1, 2, 3]


def test_a_pool_with_no_workers_is_refused():
    with pytest.raises(ValueError):
        ThreadPoolRunner(max_workers=0)


def test_shutting_down_twice_is_safe():
    runner = ThreadPoolRunner(max_workers=1)
    runner.run_all([lambda: 1])

    runner.shutdown()
    runner.shutdown()


def test_the_sequential_runner_cannot_interrupt_and_says_so():
    """Documented behaviour, asserted so the documentation cannot drift: a
    task that hangs on the sequential runner hangs the review, exactly as it
    did before this level existed."""
    assert "cannot honour a timeout" in (SequentialRunner.__doc__ or "")

    started = time.monotonic()
    outcomes = SequentialRunner().run_all([lambda: time.sleep(0.1) or "slow"], timeout_s=0.01)

    assert outcomes[0].value == "slow"
    assert time.monotonic() - started >= 0.1


# -- R-05: what the group deadline costs the report --------------------------
#
# The deadline is shared by the group, deliberately: ten hung tasks cost one
# timeout rather than ten. The consequence was that every task collected after
# the first timeout was reported in the same words as the task that actually
# hung, and only one of those threads is unreclaimable.


def test_a_task_collected_after_the_deadline_says_which_it_was():
    runner = ThreadPoolRunner(max_workers=1)

    outcomes = runner.run_all([lambda: time.sleep(0.5), lambda: "quick"], timeout_s=0.05)

    assert outcomes[0].timed_out
    assert "timed out after" in outcomes[0].error_type
    assert outcomes[1].timed_out
    assert "the group's deadline had already passed" in outcomes[1].error_type


def test_the_pool_is_tainted_by_the_task_that_actually_hung():
    runner = ThreadPoolRunner(max_workers=1)

    runner.run_all([lambda: time.sleep(0.5), lambda: "quick"], timeout_s=0.05)

    assert runner.is_tainted


# -- R-08: one runner, one caller --------------------------------------------
#
# `run_all` shares `_pool` and `_tainted` across calls. Two threads calling it
# on one runner would race on both: one could replace the pool the other is
# collecting from. True today because one review runs at a time per process,
# and true nowhere in writing.


def test_a_second_concurrent_call_is_refused_rather_than_racing():
    runner = ThreadPoolRunner(max_workers=2)
    inside = threading.Event()
    release = threading.Event()
    refused: list[Exception] = []

    def hold():
        inside.set()
        release.wait(timeout=2.0)
        return "held"

    def intruder():
        inside.wait(timeout=2.0)
        try:
            runner.run_all([lambda: "second"])
        except RuntimeError as error:
            refused.append(error)
        finally:
            release.set()

    other = threading.Thread(target=intruder)
    other.start()
    outcomes = runner.run_all([hold])
    other.join(timeout=2.0)

    assert outcomes[0].value == "held"
    assert refused, "the second caller was allowed in"
    assert "one caller at a time" in str(refused[0])


def test_the_runner_is_reusable_after_a_call_returns():
    """Refusing a concurrent call must not turn into refusing the next one."""
    runner = ThreadPoolRunner(max_workers=2)

    assert runner.run_all([lambda: 1])[0].value == 1
    assert runner.run_all([lambda: 2])[0].value == 2
