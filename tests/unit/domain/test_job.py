"""Step 1 — a job's lifecycle, and everything it refuses to do."""

from datetime import datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.job import JobState, ReviewJob, ReviewTarget, successors

NOW = datetime(2026, 8, 9, 12, 0, 0)
LATER = datetime(2026, 8, 9, 12, 5, 0)


def _job(**overrides) -> ReviewJob:
    defaults = {
        "job_id": "job-1",
        "target": ReviewTarget(project_id=17, merge_request_iid=42, head_sha="abc123"),
        "submitted_at": NOW,
    }
    return ReviewJob(**{**defaults, **overrides})


# -- the target --------------------------------------------------------------


def test_a_target_is_a_commit_not_a_merge_request():
    """Two requests at different head commits are two reviews, because the
    code changed. Collapsing them would silently drop the second."""
    first = ReviewTarget(project_id=17, merge_request_iid=42, head_sha="abc")
    second = ReviewTarget(project_id=17, merge_request_iid=42, head_sha="def")

    assert first.key != second.key


def test_the_same_commit_is_the_same_target():
    assert ReviewTarget(17, 42, "abc").key == ReviewTarget(17, 42, "abc").key


def test_a_target_with_no_sha_still_has_a_key():
    assert ReviewTarget(17, 42).key


def test_different_merge_requests_are_different_targets():
    assert ReviewTarget(17, 42, "abc").key != ReviewTarget(17, 43, "abc").key


# -- the lifecycle -----------------------------------------------------------


def test_a_new_job_is_queued_and_has_no_verdict():
    job = _job()

    assert job.state is JobState.QUEUED
    assert job.verdict == ""
    assert job.exit_code is None


def test_a_job_runs_and_then_succeeds():
    finished = _job().started(NOW, trace_id="17-42").succeeded(LATER, verdict="pass", exit_code=0)

    assert finished.state is JobState.SUCCEEDED
    assert finished.verdict == "pass"
    assert finished.exit_code == 0
    assert finished.trace_id == "17-42"
    assert finished.finished_at == LATER


def test_a_job_runs_and_then_fails():
    failed = _job().started(NOW).failed(LATER, reason="ForgeError: 502", exit_code=3)

    assert failed.state is JobState.FAILED
    assert "502" in failed.failure_reason
    assert failed.exit_code == 3


def test_a_queued_job_may_fail_without_ever_running():
    """A shutdown, or a request that could not be scheduled."""
    failed = _job().failed(LATER, reason="the service is shutting down")

    assert failed.state is JobState.FAILED


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (JobState.QUEUED, JobState.SUCCEEDED),
        (JobState.QUEUED, JobState.QUEUED),
        (JobState.RUNNING, JobState.QUEUED),
        (JobState.RUNNING, JobState.RUNNING),
        (JobState.SUCCEEDED, JobState.RUNNING),
        (JobState.SUCCEEDED, JobState.FAILED),
        (JobState.FAILED, JobState.RUNNING),
        (JobState.FAILED, JobState.SUCCEEDED),
    ],
)
def test_an_illegal_transition_is_refused(start, target):
    """A worker that moves a finished job back to running is a bug, and the
    moment it is attempted is the moment to say so."""
    job = _job(state=start, failure_reason="x" if start is JobState.FAILED else "")

    with pytest.raises(ValueError):
        job.transition_to(target)


@given(st.sampled_from(list(JobState)), st.sampled_from(list(JobState)))
def test_exactly_the_documented_successors_are_accepted(start, target):
    job = _job(state=start, failure_reason="x" if start is JobState.FAILED else "")

    if target in successors(start):
        assert job.transition_to(target, failure_reason="x").state is target
    else:
        with pytest.raises(ValueError):
            job.transition_to(target, failure_reason="x")


def test_the_refusal_names_what_was_possible():
    with pytest.raises(ValueError) as error:
        _job(state=JobState.SUCCEEDED).transition_to(JobState.RUNNING)

    assert "succeeded" in str(error.value)
    assert "nothing" in str(error.value)


# -- what a job may and may not carry ---------------------------------------


def test_a_failed_job_must_say_why():
    """The same rule a failed AgentReport follows."""
    with pytest.raises(ValueError):
        _job(state=JobState.FAILED)


def test_an_unfinished_job_may_not_carry_an_exit_code():
    """Zero is a verdict. `None` is 'not yet', and the two must not be the
    same value."""
    with pytest.raises(ValueError):
        _job(state=JobState.RUNNING, exit_code=0)


def test_a_final_state_knows_it_is_final():
    assert JobState.SUCCEEDED.is_final
    assert JobState.FAILED.is_final
    assert not JobState.QUEUED.is_final
    assert not JobState.RUNNING.is_final


# -- identity ----------------------------------------------------------------


def test_a_jobs_key_is_its_target_by_default():
    assert _job().key == ReviewTarget(17, 42, "abc123").key


def test_an_explicit_idempotency_key_wins():
    """Two differing bodies under one key are one job."""
    assert _job(idempotency_key="chosen").key == "chosen"


def test_jobs_are_values():
    assert _job() == _job()
