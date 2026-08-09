# Level 19 — Plan

Branch: `feature/level-19-deployment`, off `development`, merged with `--no-ff`.

## Step 1 — What readiness is

*Tests* — `tests/unit/domain/test_readiness.py`

- A `CheckResult` carries a name, whether it passed, and a reason when it did
  not. A failure without a reason is refused, as everywhere else in this
  package.
- AC-1: a `Readiness` of all-passing results is ready and has no reasons.
- AC-2: a `Readiness` with three failures reports three reasons, not one.
- AC-5: reasons come back in check-name order, so two runs read alike.
- An empty `Readiness` is ready — a process with nothing to check has nothing
  wrong with it, and defaulting to "not ready" would make the first deployment
  of anything fail.
- A one-line summary names the failing checks and nothing else.

*Change* — `code_reviewer/domain/health.py`: `CheckResult`, `Readiness`.

## Step 2 — Running the checks

*Tests* — `tests/unit/application/test_readiness_probe.py`

- Registered checks run in registration order and produce one result each.
- AC-3: a check that raises fails only itself, with the exception's type as the
  reason, and the others still run.
- A check that returns something that is not a `CheckResult` fails with a
  stated reason rather than corrupting the aggregate.
- A probe with no checks is ready.
- The probe is safe to call from two threads — it is what a probe *is*.

*Change* — `application/health.py`: `ReadinessProbe`.

## Step 3 — What this deployment actually needs

*Tests* — `tests/unit/infrastructure/test_deployment_settings.py`

- AC-6: with nothing set, the check names every missing variable.
- With everything set, it passes.
- AC-4: with everything set to obvious secrets, no reason and no repr contains
  any of their values — asserted against the *values*, so a future change that
  starts echoing them fails here.
- A variable set to whitespace counts as missing: `GITLAB_TOKEN=" "` is a
  configuration error dressed as a value.
- The writable-workspace check fails when the configured root does not exist.

*Change* — `infrastructure/deployment/settings.py`: the checks a running
container needs, and a factory that assembles the probe.

## Step 4 — Draining on a signal

*Tests* — `tests/unit/test_serve_shutdown.py`

- AC-15: the handler stops the server, stops the worker, and returns 0.
- AC-16: a worker that does not finish within the bound is logged and the
  process still exits.
- A second signal does not restart the drain.
- The handler is installed for `SIGTERM` and `SIGINT`.

*Change* — `serve.py`: signal handling and a bounded drain, plus
`--drain-seconds`.

## Step 5 — The image

*Files* — `Dockerfile`, `.dockerignore`

Two stages. The first resolves the lock file with `uv` and installs into a
virtual environment; the second copies that environment onto a slim base,
creates a non-root user, and runs `gunicorn` — no compiler, no `uv`, no source
tree, no `.git`.

## Step 6 — The manifests

*Files* — `deploy/kubernetes/*.yaml`

`namespace`, `configmap`, `secret.example`, `deployment`, `service`. Each key in
the `ConfigMap` carries a comment saying what breaks without it.

## Step 7 — Asserting on both

*Tests* — `tests/unit/test_deployment_manifests.py`

- AC-8, AC-9, AC-10: a non-root `USER`, no `latest` in any `FROM`, and nothing
  in the final stage that compiles.
- AC-11: the probe paths in the deployment are paths in `ReviewApi.ROUTES`, and
  the container port is the one the command serves. A renamed endpoint breaks
  the test rather than the cluster.
- AC-12: requests, limits, `runAsNonRoot`, `allowPrivilegeEscalation: false`,
  `readOnlyRootFilesystem`, every capability dropped.
- AC-13: no manifest carries a literal credential — every secret is a
  `secretKeyRef`, and the example `Secret`'s values are placeholders.
- AC-14: every file parses, and carries `apiVersion`, `kind` and a name.
- The deployment asks for one replica, and the manifest says why.

## Step 8 — CI and documentation

- A `docker build` step in the GitHub workflow (build only; where it is pushed
  is not this repository's decision).
- `docs/adr/0021-a-deployment-that-is-tested.md`: D-1, D-2, D-4, D-5.
- `docs/ARCHITECTURE.md`, `README.md`, `CHANGELOG.md`,
  `docs/roadmap/README.md`.

## Order and rationale

Steps 1–3 come first because they are the part with behaviour: `/readyz` has
been answering "ready" from a lambda since Level 18, and a container wired to a
probe that always passes is worse than a container with no probe at all — it
receives traffic while unconfigured.

Step 4 is the other half of the same problem: Kubernetes' contract is a signal
and thirty seconds, and a process that ignores both loses a review on every
rollout.

Steps 5–7 are the artefacts and the tests that keep them honest. The tests come
after the files for once, because the properties worth asserting are properties
*of* a specific file, and writing the assertions first would be writing them
against a file this level had not yet decided the shape of.
