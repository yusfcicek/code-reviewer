# 0021 — A deployment that is tested

Status: Accepted
Date: 2026-08-09
Level: [19](../roadmap/level-19/spec.md)

## Context

Level 18 made the review callable. Nothing made it deployable, and two of the
gaps were worse than merely missing.

`/readyz` returned `(True, "ready")` from a lambda. The process could be
missing its GitLab token, its model endpoint and its policy file and still
report itself ready to take work — and Kubernetes would then route to it. A
container wired to a probe that always passes is worse than a container with no
probe at all.

`SIGTERM` was unhandled. Kubernetes sends one and waits thirty seconds; the
process died at the first signal with a review half-run, its comment unposted
and its job stuck in `RUNNING` forever.

And nothing stated how it should be run: which user, which port, which limits,
where the secrets come from.

## Decision

### The manifests are tested, not merely written

A Dockerfile that claims a non-root user and a deployment that claims a
readiness path are both *claims*. This repository's oldest rule is that
documentation may never claim behaviour the code does not have, and a manifest
is documentation that a cluster executes.

So `tests/unit/test_deployment_manifests.py` parses both and asserts the
properties that matter: a numeric non-root `USER`, no `latest` in any `FROM`,
no build toolchain surviving into the runtime stage, requests and limits,
`runAsNonRoot`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem`,
every capability dropped, no literal secret anywhere, and — the one that pays
for the rest — **the probe paths compared against `ReviewApi.ROUTES`**. Rename
an endpoint and a test fails; without it, a cluster fails.

It also asserts that the two probe paths are exactly the two *open* routes, so
nobody can wire a probe to something that needs a token.

### Readiness is a first-class object

Named checks, each isolated. A check that raises fails *itself* — a readiness
endpoint that returns 500 because a check had a bug takes the deployment down
for a reason unrelated to readiness. A check that returns the wrong shape is a
failed check rather than a corrupt aggregate.

Every failure is reported, not the first: a probe that names one missing
variable per deploy costs a deploy per variable.

And a reason names the *setting*, never its value. `/readyz` is
unauthenticated, and a probe that echoes configuration is a configuration
endpoint. The test asserts against the configured values themselves, so a
future change that starts printing them fails there rather than in a
screenshot.

### One replica, and no autoscaler

The queue is in memory. Two replicas do not share it: a review submitted to one
is invisible to the other, and a status request routed to the second answers
404 for a job the first is running. Scaling needs a shared store, which is
Level 18's stated open decision.

Shipping a `HorizontalPodAutoscaler` would be a bug delivered as
configuration. The deployment asks for one replica, uses the `Recreate`
strategy for the same reason, and says so in a comment — and a test asserts
that no autoscaler is present.

### Drain, then give up, and say which happened

`SIGTERM` stops the server and gives the worker a bounded time to finish the
review in flight. Past the bound it stops waiting and logs it.

A shutdown that waits forever is a pod that gets `SIGKILL`ed anyway, with the
same review half-run and nothing in the log about it. The bounded version is
strictly more informative and no less correct. `terminationGracePeriodSeconds`
is set above the drain bound, and a test asserts that ordering — the two
numbers are in different files and would otherwise drift.

The handler starts a thread to call `server.shutdown()`, because
`serve_forever` blocks the main thread and `shutdown` waits for that loop:
asking from a handler that runs *on* the main thread deadlocks.

### `gunicorn` is an extra, and it is audited

The image runs `gunicorn`, not `wsgiref` — one request at a time is fine for a
laptop and not for a deployment. It is an optional extra so that a pipeline
running `ai-code-review` does not carry a web server, and it is *also* in the
dev group so the lock file pins it and the dependency audit sees it. The thing
the image ships has to be audited by the same job that audits everything else.

## Consequences

**No Helm chart.** Six plain manifests a reader can read. A chart is a
templating language on top of a templating language, and it earns itself when
environments genuinely differ. This one has no variants yet.

**No ingress and no TLS.** The container serves plain HTTP and expects
something in front of it. Terminating TLS in the application would be a second
place to get it wrong.

**CI builds the image and does not push it.** That it builds is a property of
this repository; where it goes and what deploys it belong to whoever operates
it.

**The image is not run in a test.** Asserting on a running container needs a
runtime in the test environment, and every property worth asserting is readable
from the file. What CI proves is that it builds.

**A read-only root filesystem needs writable mounts, and they are declared.**
`/tmp` and `/workspace`, both `emptyDir`. A test asserts both are mounted,
because "we set `readOnlyRootFilesystem`" and "the process can still run" are
two claims and only one of them is usually checked.

**The project memory degrades to empty on a restart unless its path is a
persistent mount.** The `ConfigMap` says so where the path is set. That is
correct behaviour — Level 14 said a fresh clone has no history — and it is
worth knowing before concluding the feature does nothing.
