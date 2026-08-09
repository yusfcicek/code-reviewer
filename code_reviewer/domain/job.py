"""One request for a review, and what may happen to it.

A review takes minutes, so a service cannot answer with one. It answers with a
job, and the job is the thing a caller asks about afterwards.

Which transitions are legal is a rule about jobs, not about HTTP, and it lives
here for the reason every rule in this package does: it needs no server and no
clock to test. It also stops a specific bug the rest of the level would
otherwise be free to produce — a worker that moves a finished job back to
running, which is the kind of thing that is noticed three weeks later in a
metric nobody trusts (decision D-2).

The identity of a job is its target, and a target is a *commit*, not a merge
request. Two requests for the same merge request at different head commits are
two reviews, because the code changed; collapsing them would silently drop the
second, and a review that never happened with nothing to see is the worst
failure this service can have (decision D-3).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class JobState(Enum):
    """Where a review request has got to."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_final(self) -> bool:
        return self in (JobState.SUCCEEDED, JobState.FAILED)


#: The only transitions there are. Anything else is a bug in whoever attempted
#: it, and the moment it is attempted is the moment to say so.
_ALLOWED: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.FAILED}),
    JobState.RUNNING: frozenset({JobState.SUCCEEDED, JobState.FAILED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
}


def successors(state: JobState) -> frozenset[JobState]:
    """The states this one may become."""
    return _ALLOWED[state]


@dataclass(frozen=True)
class ReviewTarget:
    """What a review is of."""

    project_id: int
    merge_request_iid: int
    #: The commit under review. Part of the identity: a merge request that has
    #: been pushed to is a different review (decision D-3).
    head_sha: str = ""

    @property
    def key(self) -> str:
        """What makes two requests the same request."""
        return f"{self.project_id}/{self.merge_request_iid}@{self.head_sha or 'head'}"


@dataclass(frozen=True)
class ReviewJob:
    """One review, from asked-for to answered."""

    job_id: str
    target: ReviewTarget
    state: JobState = JobState.QUEUED
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: The gate's verdict, once there is one. ``""`` while there is not —
    #: distinct from a verdict of "pass", which is a fact.
    verdict: str = ""
    exit_code: int | None = None
    failure_reason: str = ""
    trace_id: str = ""
    #: What the request supplied, when it supplied one. Two different targets
    #: under one key are one job.
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        if self.state is JobState.FAILED and not self.failure_reason:
            raise ValueError(f"Job {self.job_id} failed without saying why.")
        if not self.state.is_final and self.exit_code is not None:
            raise ValueError(f"Job {self.job_id} is not finished and cannot have an exit code.")

    @property
    def key(self) -> str:
        """What this job is identified by for idempotency."""
        return self.idempotency_key or self.target.key

    def transition_to(self, state: JobState, **changes) -> "ReviewJob":
        """This job, moved. Refuses anything that is not a legal move."""
        if state not in _ALLOWED[self.state]:
            raise ValueError(
                f"Job {self.job_id} cannot go from {self.state.value} to {state.value}. "
                f"From {self.state.value} it may only become "
                f"{sorted(item.value for item in _ALLOWED[self.state]) or ['nothing']}."
            )
        return replace(self, state=state, **changes)

    def with_trace(self, trace_id: str) -> "ReviewJob":
        """This job, told which trace it is being run under.

        Not a transition: naming the trace does not move the job, and routing
        it through `transition_to` would mean inventing a state-to-itself move
        that the rules deliberately refuse.
        """
        return replace(self, trace_id=trace_id)

    def started(self, when: datetime, trace_id: str = "") -> "ReviewJob":
        return self.transition_to(JobState.RUNNING, started_at=when, trace_id=trace_id)

    def succeeded(self, when: datetime, verdict: str, exit_code: int) -> "ReviewJob":
        return self.transition_to(JobState.SUCCEEDED, finished_at=when, verdict=verdict, exit_code=exit_code)

    def failed(self, when: datetime, reason: str, exit_code: int | None = None) -> "ReviewJob":
        return self.transition_to(
            JobState.FAILED, finished_at=when, failure_reason=reason, exit_code=exit_code
        )
