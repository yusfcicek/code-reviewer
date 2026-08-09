# Level 19 — Containerisation & cloud-native deployment

## Problem statement

Level 18 made the review callable. Nothing yet makes it deployable.

- **There is no image.** Running this anywhere means cloning the repository,
  installing a Python, resolving a lock file and hoping the host has the same
  interpreter. Every source names Docker, Kubernetes and OpenShift; none of
  them can start from a `git clone` (C-16).
- **`/readyz` is a lie by omission.** It returns `(True, "ready")` from a
  lambda. The process can be missing its GitLab token, its model endpoint and
  its policy file and still report itself ready to take work — which is the
  worst possible answer, because Kubernetes will then route to it.
- **`SIGTERM` is unhandled.** Kubernetes sends one and waits thirty seconds
  before killing the container. Today the process dies at the first signal with
  a review half-run, its comment unposted and its job stuck in `RUNNING`
  forever (C-17).
- **Nothing states how it should be run.** Which user, which port, which
  resource limits, which probes, where the secrets come from — all of it lives
  in whatever a reader guesses.

Capabilities addressed: **C-16, C-17**.

## Goals

1. A multi-stage image that runs as a non-root user and carries no build
   toolchain.
2. Kubernetes manifests that wire the two probes the service already has,
   set limits, and take every secret from a `Secret`.
3. `/readyz` answers from real checks, and names what is missing.
4. `SIGTERM` drains: the service stops accepting, lets the running review
   finish within a bound, and exits cleanly.
5. Every claim above is asserted by a test, not by a paragraph.

## Non-goals

- **A Helm chart.** Six plain manifests are readable by anyone; a chart is a
  templating language on top of a templating language, and this deployment has
  no variants yet. When there are three environments that genuinely differ, a
  chart earns itself.
- **A registry, a pipeline that pushes, or an environment.** CI builds the
  image to prove it builds. Where it is pushed and what deploys it are
  decisions belonging to whoever operates it.
- **A service mesh, an ingress, or TLS termination.** The container serves
  plain HTTP on a loopback-friendly port and expects something in front of it.
  Terminating TLS in the application would be a second place to get it wrong.
- **Horizontal autoscaling.** The queue is in memory, so two replicas do not
  share it: a review submitted to one is invisible to the other. Scaling
  needs the store to be a shared one, which is Level 18's stated open
  decision. A manifest that scaled anyway would be a bug shipped as
  configuration.
- **Testing that the image *runs*.** CI builds it; asserting on a running
  container needs a runtime in the test environment, and the properties worth
  asserting are all readable from the file.

## Behavioural contracts

### C-1 — Readiness is a set of checks with names (C-17)
A probe holds named checks. Each returns pass or fail with a reason. The
aggregate is ready only when all pass, and it reports every failure rather than
the first — a probe that names one missing variable at a time takes three
deploys to configure.

### C-2 — A check that raises fails its own check (C-17)
An exception inside one check is that check failing, not the probe failing. A
readiness endpoint that returns 500 because a check had a bug is a readiness
endpoint that takes the deployment down for a reason unrelated to readiness.

### C-3 — Readiness names what is missing, never its value (C-17)
"GITLAB_TOKEN is not set" is the reason. The value of a variable that *is* set
never appears — `/readyz` is unauthenticated, and a probe that echoes
configuration is a configuration endpoint.

### C-4 — The image runs as a non-root user (C-16)
A `USER` that is not root, a home it can write to, and no build toolchain in
the final stage. Asserted by parsing the Dockerfile, because "we set USER" is
the kind of claim that survives its own deletion.

### C-5 — The image pins what it is built from (C-16)
No `latest` tag in any `FROM`. An image that rebuilds differently next Tuesday
is not a deployable artefact.

### C-6 — The manifests wire the probes that exist (C-16)
The liveness and readiness paths in the deployment are paths the application
actually serves, and the port is the port it listens on. Asserted by comparing
the manifest against `ReviewApi.ROUTES`, so a renamed endpoint breaks the test
rather than the cluster.

### C-7 — The manifests set limits and a security context (C-16)
CPU and memory requests and limits, `runAsNonRoot`, `allowPrivilegeEscalation:
false`, a read-only root filesystem, and every capability dropped. A container
without limits is a container that takes its node down with it.

### C-8 — No secret is a literal in a manifest (C-16)
Every credential comes from a `secretKeyRef`. The shipped `Secret` is an
example with placeholder values and says so in its name and its comments.

### C-9 — `SIGTERM` drains rather than kills (C-17)
On the signal the service stops the server, gives the worker a bounded time to
finish the review in flight, and exits `0`. Past the bound it stops waiting and
says so — a shutdown that hangs is a pod that gets `SIGKILL`ed with the same
review half-run, and the honest version at least logs it.

### C-10 — The container's own configuration is documented where it is used
The manifest carries a comment per setting explaining what breaks without it,
because a `ConfigMap` with twelve unexplained keys is twelve keys nobody dares
change.

## Acceptance criteria

| # | Criterion | Verified by |
|---|---|---|
| AC-1 | A probe with all checks passing is ready | Unit test |
| AC-2 | A probe reports *every* failing check, not the first | Unit test |
| AC-3 | A check that raises fails only itself | Unit test |
| AC-4 | Reasons never contain a configured value | Unit test over a set environment |
| AC-5 | The order of reasons is deterministic | Unit test |
| AC-6 | The settings check names each missing variable | Unit test |
| AC-7 | `/readyz` is 503 with the reasons when a check fails | Unit test on the app |
| AC-8 | The Dockerfile sets a non-root `USER` | Manifest test |
| AC-9 | No `FROM` uses `latest` | Manifest test |
| AC-10 | The final stage carries no build toolchain | Manifest test |
| AC-11 | The deployment's probe paths are paths the app serves | Manifest test against the route table |
| AC-12 | The deployment sets requests, limits and a security context | Manifest test |
| AC-13 | No manifest contains a literal secret value | Manifest test |
| AC-14 | Every manifest is valid YAML with the fields Kubernetes requires | Manifest test |
| AC-15 | `SIGTERM` drains the worker and exits 0 | Unit test |
| AC-16 | A drain past its bound is logged and still exits | Unit test |
| AC-17 | CI builds the image | GitHub workflow |
| AC-18 | The six checks stay green, coverage holds, the eval floors hold | `ruff`, `mypy`, `pytest --cov`, audit, eval |

## Decisions taken

**D-1 — The manifests are tested, not just written.** A Dockerfile that claims
a non-root user and a manifest that claims a readiness path are both claims,
and this repository's rule is that documentation may never claim behaviour the
code does not have. Parsing them in a test costs twenty lines and catches the
rename that would otherwise be caught by a cluster.

**D-2 — Readiness is a first-class object, not a lambda.** Level 18 left
`ready=lambda: (True, "ready")` because it had nothing to check. It has
something now, and a probe that reports every failure at once is the difference
between one deploy and three.

**D-3 — Plain manifests, not Helm.** Six files a reader can read. A chart is
worth its templating when environments genuinely differ, and this one has no
variants yet.

**D-4 — No autoscaling manifest.** The queue is in memory: two replicas do not
share it, and a review submitted to one is invisible to the other. Shipping an
`HorizontalPodAutoscaler` would be a bug delivered as configuration. The
manifest sets `replicas: 1` and says why.

**D-5 — Drain, then give up, and say which happened.** A shutdown that waits
forever is a pod that gets `SIGKILL`ed anyway, with the same review half-run
and no record of it. A bounded wait plus a log line is strictly more
informative and no less correct.

**D-6 — `uv` in the build stage, nothing in the final one.** The final image
carries the interpreter, the installed package and its runtime dependencies.
No compiler, no `uv`, no source tree, no `.git`.
