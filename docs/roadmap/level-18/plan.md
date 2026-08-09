# Level 18 — Plan

Branch: `feature/level-18-service`, off `development`, merged with `--no-ff`.

## Step 1 — What a job is

*Tests* — `tests/unit/domain/test_job.py`

- A `ReviewJob` carries its id, what it is reviewing, its state and its times.
- AC-1: `QUEUED → RUNNING → SUCCEEDED`, `QUEUED → RUNNING → FAILED`.
- AC-1: every other transition is refused — `SUCCEEDED → RUNNING`,
  `QUEUED → SUCCEEDED`, and a state to itself.
- AC-1 (property): from any state, exactly the documented successors are
  accepted and no others.
- A finished job carries a verdict and an exit code; an unfinished one carries
  neither, rather than carrying zero.
- A failed job carries a reason, in the way a failed `AgentReport` does.
- The idempotency key is the project, the merge request and the head commit —
  and two jobs for the same merge request at different commits have different
  keys (D-3).

*Change* — `code_reviewer/domain/job.py`: `JobState`, `ReviewJob`,
`ReviewTarget`.

## Step 2 — The queue and the service

*Tests* — `tests/unit/application/test_job_service.py`

- AC-4: submitting the same target twice returns the first job.
- AC-6: once a job has finished, the same target submits a new one.
- AC-5: an explicit idempotency key collapses two differing targets.
- AC-9: past its depth, submitting raises `QueueFull`.
- `claim()` takes the oldest queued job and moves it to `RUNNING`; with nothing
  queued it returns `None` rather than blocking.
- Completing a job records its verdict; failing one records its reason.
- Every operation is safe under contention — eight threads submitting the same
  target produce one job, and eight claiming produce eight distinct ones.

*Change* — `application/jobs.py`: `JobStore` port, `InMemoryJobStore`,
`JobService`, `QueueFull`.

## Step 3 — The application

*Tests* — `tests/unit/infrastructure/test_http_app.py`

Called as a WSGI callable with a dictionary. No client, no server, no loop.

- AC-2, AC-3: a valid POST is 202 with an id and a `Location`; malformed JSON,
  a missing field and a wrong type are each 400 with a stated reason.
- AC-7, AC-8: status reports state and verdict, never the comment; unknown is
  404.
- AC-13: every authenticated route answers 401 without a token and with a
  wrong one — asserted over the route table rather than one route at a time,
  so a route added later is covered by construction.
- AC-14, AC-15: `/healthz` and `/readyz` need no token and answer different
  questions; readiness is 503 when the queue is saturated.
- AC-16: an oversized body is 413 and is not read.
- AC-17: `/metrics` is OpenMetrics text with the right content type.
- An unknown path is 404 and an unsupported method is 405 with `Allow`.
- Every response is JSON except `/metrics`, and every error names what was
  wrong without quoting the request.

*Change* — `infrastructure/http/app.py`: `ReviewApi`, a WSGI callable.

## Step 4 — The webhook

*Tests* — `tests/unit/infrastructure/test_webhook.py`

- AC-10: a wrong token is 401, and the body is never parsed — asserted by
  sending a body that would raise if it were.
- AC-11: the right token and a merge-request `open` enqueue a review with the
  project, the iid and the head sha from the payload.
- AC-12: a `close`, a push event, and an unknown object kind are 204 and
  enqueue nothing.
- A payload missing the fields the review needs is 400, not 500.
- With no secret configured, the endpoint refuses everything — an unset secret
  is a misconfiguration, and defaulting to "accept" would be the worst reading
  of it.

*Change* — the webhook route in the same module, and
`infrastructure/http/gitlab_events.py` for the payload reading.

## Step 5 — The worker

*Tests* — `tests/unit/infrastructure/test_review_worker.py`

- AC-18: a queued job is claimed, run through `ReviewService`, and recorded
  with its verdict and exit code.
- AC-19: a review that raises marks the job failed with the exception's type,
  and the worker keeps draining.
- Stopping the worker drains nothing further and returns promptly.
- Each job runs inside its own trace, and the job records the trace id.

*Change* — `infrastructure/http/worker.py`: `ReviewWorker`, one thread.

## Step 6 — Serving it

*Tests* — `tests/unit/test_serve_cli.py`

- The entry point builds an application and a worker and does not start a
  server when asked to build only.
- `--host`, `--port`, `--queue-depth` and the token come from flags or the
  environment.
- Starting without `REVIEW_API_TOKEN` refuses to serve rather than serving
  unauthenticated.

*Change* — `code_reviewer/serve.py` and the `ai-code-review-serve` entry point.

## Step 7 — Documentation

- `docs/adr/0020-a-wsgi-application-not-a-framework.md`: D-1, D-3, D-4, D-5.
- `docs/ARCHITECTURE.md`, `README.md` (the route table), `CHANGELOG.md`,
  `docs/roadmap/README.md`.

## Order and rationale

Step 1 is the only domain work and it is the one that stops a class of bug the
rest of the level would otherwise produce: a worker that moves a finished job
back to running.

Step 3 comes before the webhook and the worker because the routing, the
authentication and the error shape are what every later route inherits, and
because a route table that is tested as a table is a route table where adding a
route cannot quietly skip authentication.

Step 5 is last of the code because it is the only part that ties the service to
the review, and by then both halves are already proven separately.
