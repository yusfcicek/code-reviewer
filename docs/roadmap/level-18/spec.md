# Level 18 — Service surface

## Problem statement

This is a command-line program. The only way to ask it for a review is to run
it, from a pipeline, with the merge request's identifiers on the command line.

That is a real limitation and not a stylistic one.

- **Nothing else can ask for a review.** A bot, a scheduler, a chat command, a
  second pipeline, a person with a browser: each would need a runner, a
  checkout and a set of CI variables to do what is conceptually one request
  (C-14).
- **A review can only be triggered by the thing that already knows the
  identifiers.** GitLab emits a merge-request webhook the moment one opens.
  Nothing here can receive it, so the trigger has to be re-derived inside a
  pipeline that the same event started anyway (C-15).
- **The process has nothing to say about itself.** Kubernetes asks a container
  whether it is alive and whether it is ready; this one cannot answer, so it
  cannot be deployed as anything but a job (C-16, and the reason Level 19
  cannot start).
- **Concurrency stops at the file.** Level 17 made a committee overlap its
  waiting. A service can overlap whole reviews — but only if there is
  something to submit them to.

Capabilities addressed: **C-14, C-15**, and the precondition for **C-16**.

## Goals

1. A review can be requested over HTTP, and its progress read back.
2. A GitLab merge-request webhook starts one, with its secret verified.
3. The process answers liveness and readiness, and exports its metrics.
4. The same request twice is one review, not two.
5. Nothing about the review itself changes: the same service, the same gate,
   the same verdict.

## Non-goals

- **A web framework.** FastAPI is the industry answer and this level does not
  take it, for the third time in this roadmap and with the same reasoning
  written down (D-1). What ships is a WSGI application: the standard interface
  every Python server speaks, no runtime dependency, and a hundred lines this
  repository owns. It runs under gunicorn or uvicorn in a container, which is
  a deployment choice rather than a source dependency.
- **A database.** Job state is in memory, and the process says so: a restart
  loses what was queued. Persisting it is a decision about operating the
  service, and it belongs with the deployment work rather than in front of it.
- **gRPC.** Named by the sources, and the answer is the same as for the
  framework: the port is `ReviewService`, which knows nothing about HTTP, so a
  gRPC adapter is a sibling module. One protocol at a time, and REST is the one
  a webhook speaks.
- **Multi-tenancy, quotas, or a user model.** One token, one deployment, one
  team. Anything else is a product decision nobody has made.
- **Streaming progress.** A review takes minutes and produces one comment. A
  status endpoint answers "is it done" without a second protocol.

## Behavioural contracts

### C-1 — A job has a lifecycle, and it is a domain rule (C-14)
`QUEUED → RUNNING → SUCCEEDED | FAILED`, and nothing else. A transition that is
not one of those is refused rather than silently applied: a job that goes from
`SUCCEEDED` back to `RUNNING` is a bug in the worker, and the place to notice
it is the moment it is attempted.

### C-2 — `POST /reviews` accepts and returns immediately (C-14)
A review takes minutes. The request is validated, enqueued, and answered `202`
with the job's identifier and a `Location`. A body that is not valid JSON, or
that omits an identifier, is `400` with a stated reason.

### C-3 — The same request twice is one review (C-14)
Two requests naming the same project, merge request and head commit while the
first is still queued or running return the *same* job and `200` rather than
enqueuing a second. A caller may also supply `Idempotency-Key` and get the same
guarantee across differing bodies.

### C-4 — `GET /reviews/{id}` reports without leaking (C-14)
State, verdict, exit code, trace id, when it started and finished. Not the
comment: it may contain quoted source, and an endpoint that returns it is a
second place to get a diff out of the process. Anything unknown is `404`.

### C-5 — The queue is bounded, and says so when it is full (C-14)
Past its depth, `POST /reviews` answers `429` with `Retry-After`. A queue that
grows without bound is a memory leak with a REST interface.

### C-6 — A webhook is verified before it is believed (C-15)
`POST /webhooks/gitlab` compares `X-Gitlab-Token` against the configured secret
in constant time and answers `401` when it does not match — before parsing the
body. An event that is not a merge-request open or update is accepted and
ignored with `204`, because a webhook that returns an error for events it does
not care about gets disabled by whoever is watching the delivery log.

### C-7 — Everything else needs a bearer token (C-14)
`Authorization: Bearer …`, compared in constant time. Missing or wrong is
`401`. `/healthz` and `/readyz` are open, because a probe that needs a secret
is a probe that fails during a secret rotation.

### C-8 — Liveness and readiness are different questions (C-16)
`/healthz` answers "this process is running". `/readyz` answers "it can accept
work": policy loaded, workspace present, queue not saturated. Neither calls
GitLab — a readiness check that depends on a third party takes the deployment
down when the third party is slow.

### C-9 — Bodies are bounded (C-14)
A request larger than a stated limit is `413` and is not read into memory. The
body of a webhook comes from outside; the rule Level 8 applied to a diff
applies to a payload.

### C-10 — The service is one adapter (C-14)
It calls `ReviewService.review` and nothing else. No gate logic, no policy, no
report rendering. A second protocol is a second module in the same package.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | Legal transitions are allowed; every other one is refused | Unit + property test |
| AC-2 | A valid `POST /reviews` returns 202 with an id and a Location | Unit test |
| AC-3 | Malformed JSON, a missing field or a bad type is 400 with a reason | Unit test |
| AC-4 | The same project/mr/sha twice returns 200 and the first job | Unit test |
| AC-5 | An `Idempotency-Key` collapses two differing bodies into one job | Unit test |
| AC-6 | A completed job's identity does not block a new request | Unit test |
| AC-7 | `GET /reviews/{id}` reports state and verdict, and never the comment | Unit test |
| AC-8 | An unknown id is 404 | Unit test |
| AC-9 | A full queue answers 429 with `Retry-After` | Unit test |
| AC-10 | A webhook with a wrong token is 401 before the body is parsed | Unit test |
| AC-11 | A webhook with the right token enqueues a review | Unit test |
| AC-12 | An irrelevant event is 204 and enqueues nothing | Unit test |
| AC-13 | Every authenticated route rejects a missing or wrong token | Unit test over the route table |
| AC-14 | `/healthz` and `/readyz` need no token, and answer different questions | Unit test |
| AC-15 | `/readyz` is 503 when the queue is saturated | Unit test |
| AC-16 | An oversized body is 413 | Unit test |
| AC-17 | `/metrics` returns OpenMetrics text | Unit test |
| AC-18 | The worker runs a queued job and records its outcome | Unit test |
| AC-19 | A worker that raises marks the job failed and keeps draining | Unit test |
| AC-20 | The six checks stay green, coverage holds, the eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — A WSGI application, not a framework.** FastAPI would bring starlette,
pydantic, anyio and a dozen transitive packages into a process whose dependency
audit runs with an empty ignore list, to serve six endpoints whose bodies have
two fields each. WSGI is the standard interface: the same application runs
under gunicorn, uvicorn or `wsgiref` unchanged, and it is testable by calling
it with a dictionary — no client, no event loop, no test server.

What that costs is stated rather than hidden: no generated OpenAPI schema, and
validation is written by hand. Both are small at six endpoints and would not
stay small at sixty, which is the point at which the decision should be
revisited.

**D-2 — The job lifecycle is a domain rule.** Which transitions are legal is
not an HTTP concern, and a worker that moves a finished job back to running is
a bug that should be caught at the transition rather than in a log.

**D-3 — Idempotency is keyed on the commit, not the merge request.** Two
requests for the same merge request at *different* head commits are two
different reviews, because the code changed. Keying on the merge request alone
would silently drop the second, which is the worst possible failure: nothing to
see, and a review that never happened.

**D-4 — The status endpoint does not return the comment.** It is rendered from
the diff and may quote it. An endpoint that returns it is a second way to get
source out of the process, guarded by one token, and the merge request already
has the comment.

**D-5 — Readiness does not call GitLab.** A readiness probe that depends on a
third party takes the deployment down when the third party is slow, which is
exactly when the deployment is most needed.

**D-6 — Job state is in memory, and the process says so.** A restart loses the
queue. Persisting it is a decision about operating the service — which store,
whose backup, whose migration — and making it here would be guessing.
