# 0020 — A WSGI application, not a framework

Status: Accepted
Date: 2026-08-09
Level: [18](../roadmap/level-18/spec.md)

## Context

This was a command-line program. Asking it for a review meant running it, from
a pipeline, with the merge request's identifiers on the command line — so a
bot, a scheduler, a chat command or a person with a browser each needed a
runner, a checkout and a set of CI variables to do what is conceptually one
request. GitLab emits a merge-request webhook the moment one opens, and nothing
here could receive it.

It also could not be deployed as anything but a job: Kubernetes asks a
container whether it is alive and whether it is ready, and this one had no way
to answer.

## Decision

### A WSGI application, not FastAPI

Third framework refusal in this roadmap, and the reasoning is written down each
time rather than assumed.

FastAPI would bring starlette, pydantic, anyio and a dozen transitive packages
into a process whose dependency audit runs with an empty ignore list, to serve
six endpoints whose bodies have two fields each. WSGI is the standard interface
every Python server speaks: the same object runs under gunicorn, uvicorn or
`wsgiref` unchanged, so the server is a *deployment* choice rather than a
source dependency — which is exactly the shape Level 19 needs.

It is also testable by calling it with a dictionary. Forty-eight tests, no
client, no event loop, no test server, no fixtures that bind a port.

What it costs is stated rather than hidden: no generated OpenAPI schema, and
validation written by hand. Both are small at six endpoints and would not stay
small at sixty, which is the point at which this decision should be revisited.
gRPC gets the same answer — the port is `ReviewService`, which knows nothing
about HTTP, so a second protocol is a sibling module.

### Idempotency is keyed on the commit

Two requests for the same merge request at *different* head commits are two
reviews, because the code changed. Keying on the merge request alone would
silently drop the second — nothing to see, and a review that never happened,
which is the worst failure this service can have.

A caller may also supply `Idempotency-Key` and get the same guarantee across
differing bodies.

Once a job has finished, the same commit may be submitted again: a retry after
a failure, or a rerun after the policy changed, are both legitimate.

### The status endpoint does not return the comment

The comment is rendered from the diff and may quote it. An endpoint that
returns it is a second way to get source out of the process, guarded by one
token — and the merge request already has it.

### Readiness does not call GitLab

`/healthz` answers "this process is running". `/readyz` answers "it can accept
work": the queue is not saturated, and the configured checks pass. Neither
calls a third party, because a readiness probe that depends on one takes the
deployment down when that party is slow, which is exactly when the deployment
is most needed.

### The job lifecycle is a domain rule

`QUEUED → RUNNING → SUCCEEDED | FAILED`, and nothing else, enforced at the
transition. A worker that moves a finished job back to running is a bug, and
the moment it is attempted is the moment to notice — not three weeks later in a
metric nobody trusts.

## Consequences

**Authentication is asserted over the route table, not per route.** `ROUTES` is
data, and the test parametrises over it, so a route added later is covered by
construction rather than by somebody remembering. The open routes are exactly
the two probes, and there is a test that says so.

**That table found a real bug.** The metrics handler was called `_metrics`, and
so was the injected collector; `getattr(self, route.handler)` resolved to the
*field*, and the endpoint returned 500. A test that submitted a zero-argument
collector caught it before anything else did.

**The webhook refuses everything when no secret is configured.** An unset
secret is a misconfiguration, and defaulting to "accept" would be the worst
reading of it. The token is compared in constant time, before the body is read
— asserted by sending a body that would raise if it were parsed.

**An event nobody asked for is 204, not an error.** An endpoint that returns
errors for events it does not care about gets disabled by whoever is watching
the delivery log.

**Nothing about a failure reaches the caller.** An unhandled exception is
`{"error": "internal error"}` and a logged stack. An error message built from
an exception is a way to learn about the inside of a process.

**Job state is in memory, and a restart loses the queue.** Persisting it is a
decision about operating the service — which store, whose backup, whose
migration — and making it here would be guessing. The store is a port; the
decision has somewhere to go.

**The service refuses to start without `REVIEW_API_TOKEN`.** Serving
unauthenticated because a variable was unset is the failure that gets found by
somebody else. The default bind address is loopback for the same reason: a
service that binds every interface by default is one that gets exposed by
accident, and a container publishes it deliberately.

**One worker, one review at a time.** A review already spends its concurrency
inside itself (Level 17); running two whole reviews at once would double the
memory and the model spend for a service whose queue depth is what actually
bounds load.
