"""Steps 3 and 4 — the surface, called as a WSGI callable.

No client, no server, no event loop: the application is a function of a
dictionary, which is the whole argument for having written it that way.
"""

import io
import itertools
import json
from datetime import UTC, datetime

import pytest

from code_reviewer.application.jobs import InMemoryJobStore, JobService
from code_reviewer.domain.job import ReviewTarget
from code_reviewer.infrastructure.http.app import BEARER, MAX_BODY_BYTES, OPEN, WEBHOOK, ReviewApi

TOKEN = "s3cret-api-token"
WEBHOOK_SECRET = "s3cret-webhook-token"
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


class Response:
    """What the application said, for a test to read."""

    def __init__(self):
        self.status = ""
        self.headers: list[tuple[str, str]] = []
        self.body = b""

    @property
    def code(self) -> int:
        return int(self.status.split()[0])

    @property
    def json(self):
        return json.loads(self.body.decode("utf-8")) if self.body else None

    def header(self, name: str) -> str | None:
        for key, value in self.headers:
            if key.lower() == name.lower():
                return value
        return None


def _call(app, method="GET", path="/healthz", body=None, headers=None) -> Response:
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(payload)),
        "wsgi.input": io.BytesIO(payload),
    }
    for name, value in (headers or {}).items():
        environ[f"HTTP_{name.upper().replace('-', '_')}"] = value

    response = Response()

    def start_response(status, response_headers):
        response.status = status
        response.headers = list(response_headers)

    chunks = app(environ, start_response)
    response.body = b"".join(chunks)
    return response


def _api(**overrides) -> tuple[ReviewApi, JobService]:
    counter = itertools.count(1)
    jobs = overrides.pop(
        "jobs",
        JobService(
            InMemoryJobStore(),
            max_queue_depth=overrides.pop("depth", 8),
            clock=lambda: NOW,
            new_id=lambda: f"job-{next(counter)}",
        ),
    )
    defaults = {"api_token": TOKEN, "webhook_secret": WEBHOOK_SECRET}
    return ReviewApi(jobs, **{**defaults, **overrides}), jobs


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# -- probes ------------------------------------------------------------------


def test_liveness_needs_no_token_and_only_claims_the_process_is_running():
    app, _ = _api()

    response = _call(app, path="/healthz")

    assert response.code == 200
    assert response.json == {"status": "alive"}


def test_readiness_needs_no_token():
    """A probe that needs a secret is a probe that fails during a secret
    rotation."""
    app, _ = _api()

    assert _call(app, path="/readyz").code == 200


def test_readiness_is_503_when_the_queue_is_saturated():
    app, jobs = _api(depth=1)
    jobs.submit(ReviewTarget(1, 1, "a"))

    response = _call(app, path="/readyz")

    assert response.code == 503
    assert "queue" in response.json["reason"]


def test_readiness_reports_a_configured_reason_when_it_is_not_ready():
    app, _ = _api(ready=lambda: (False, "the policy could not be loaded"))

    response = _call(app, path="/readyz")

    assert response.code == 503
    assert "policy" in response.json["reason"]


# -- authentication ----------------------------------------------------------


@pytest.mark.parametrize(
    "route", [route for route in ReviewApi.ROUTES if route.auth == BEARER], ids=lambda r: r.path
)
def test_every_authenticated_route_refuses_a_missing_token(route):
    """Asserted over the route table, so a route added later is covered by
    construction rather than by somebody remembering."""
    app, _ = _api()

    response = _call(app, method=route.method, path=route.path + ("x" if route.parameterised else ""))

    assert response.code == 401


@pytest.mark.parametrize(
    "route", [route for route in ReviewApi.ROUTES if route.auth == BEARER], ids=lambda r: r.path
)
def test_every_authenticated_route_refuses_a_wrong_token(route):
    app, _ = _api()

    response = _call(
        app,
        method=route.method,
        path=route.path + ("x" if route.parameterised else ""),
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.code == 401


def test_a_non_bearer_scheme_is_refused():
    app, _ = _api()

    response = _call(app, path="/metrics", headers={"Authorization": f"Basic {TOKEN}"})

    assert response.code == 401


def test_an_empty_configured_token_refuses_everyone():
    """A service that authenticates against the empty string is a service with
    no authentication and a login page."""
    app, _ = _api(api_token="")

    assert _call(app, path="/metrics", headers={"Authorization": "Bearer "}).code == 401


def test_the_open_routes_are_exactly_the_probes():
    assert {route.path for route in ReviewApi.ROUTES if route.auth == OPEN} == {"/healthz", "/readyz"}


# -- submitting --------------------------------------------------------------


def test_a_valid_submission_is_accepted_with_an_id_and_a_location():
    app, _ = _api()

    response = _call(
        app,
        method="POST",
        path="/reviews",
        body={"project_id": 17, "merge_request_iid": 42, "head_sha": "abc"},
        headers=_auth(),
    )

    assert response.code == 202
    assert response.json["id"]
    assert response.json["state"] == "queued"
    assert response.header("Location") == f"/reviews/{response.json['id']}"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({}, "project_id"),
        ({"project_id": 17}, "merge_request_iid"),
        ({"project_id": "seventeen", "merge_request_iid": 42}, "whole number"),
        ({"project_id": True, "merge_request_iid": 42}, "whole number"),
        ({"project_id": 17, "merge_request_iid": 42, "head_sha": 5}, "head_sha"),
    ],
)
def test_a_body_that_is_not_a_review_request_is_400_with_a_reason(body, expected):
    app, _ = _api()

    response = _call(app, method="POST", path="/reviews", body=body, headers=_auth())

    assert response.code == 400
    assert expected in response.json["error"]


def test_a_body_that_is_not_json_is_400():
    app, _ = _api()
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/reviews",
        "CONTENT_LENGTH": "7",
        "wsgi.input": io.BytesIO(b"{not{{{"),
        "HTTP_AUTHORIZATION": f"Bearer {TOKEN}",
    }
    response = Response()
    response.body = b"".join(
        app(environ, lambda status, headers: (setattr(response, "status", status), None)[1] or None)
    )

    assert response.status.startswith("400")


def test_an_empty_body_is_400():
    app, _ = _api()

    response = _call(app, method="POST", path="/reviews", headers=_auth())

    assert response.code == 400


def test_a_body_that_is_a_json_array_is_400():
    app, _ = _api()

    response = _call(app, method="POST", path="/reviews", body=[1, 2], headers=_auth())

    assert response.code == 400
    assert "object" in response.json["error"]


def test_an_oversized_body_is_413_and_is_not_read():
    app, _ = _api()
    stream = io.BytesIO(b"{}")
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/reviews",
        "CONTENT_LENGTH": str(MAX_BODY_BYTES + 1),
        "wsgi.input": stream,
        "HTTP_AUTHORIZATION": f"Bearer {TOKEN}",
    }
    response = Response()

    def start_response(status, headers):
        response.status = status
        response.headers = list(headers)

    response.body = b"".join(app(environ, start_response))

    assert response.code == 413
    assert stream.tell() == 0, "the body was read after being refused"


# -- idempotency -------------------------------------------------------------


def test_the_same_commit_twice_returns_the_first_job_and_200():
    app, _ = _api()
    body = {"project_id": 17, "merge_request_iid": 42, "head_sha": "abc"}

    first = _call(app, method="POST", path="/reviews", body=body, headers=_auth())
    second = _call(app, method="POST", path="/reviews", body=body, headers=_auth())

    assert first.code == 202
    assert second.code == 200
    assert second.json["id"] == first.json["id"]


def test_a_different_commit_is_a_new_review():
    app, _ = _api()

    first = _call(
        app,
        method="POST",
        path="/reviews",
        body={"project_id": 17, "merge_request_iid": 42, "head_sha": "abc"},
        headers=_auth(),
    )
    second = _call(
        app,
        method="POST",
        path="/reviews",
        body={"project_id": 17, "merge_request_iid": 42, "head_sha": "def"},
        headers=_auth(),
    )

    assert second.code == 202
    assert second.json["id"] != first.json["id"]


def test_an_idempotency_key_header_collapses_two_bodies():
    app, _ = _api()
    headers = {**_auth(), "Idempotency-Key": "chosen"}

    first = _call(
        app,
        method="POST",
        path="/reviews",
        body={"project_id": 1, "merge_request_iid": 1},
        headers=headers,
    )
    second = _call(
        app,
        method="POST",
        path="/reviews",
        body={"project_id": 2, "merge_request_iid": 2},
        headers=headers,
    )

    assert second.code == 200
    assert second.json["id"] == first.json["id"]


def test_a_full_queue_answers_429_with_retry_after():
    app, _ = _api(depth=1)
    _call(
        app,
        method="POST",
        path="/reviews",
        body={"project_id": 1, "merge_request_iid": 1},
        headers=_auth(),
    )

    response = _call(
        app,
        method="POST",
        path="/reviews",
        body={"project_id": 1, "merge_request_iid": 2},
        headers=_auth(),
    )

    assert response.code == 429
    assert response.header("Retry-After")


# -- status ------------------------------------------------------------------


def test_a_jobs_status_is_readable():
    app, jobs = _api()
    job, _ = jobs.submit(ReviewTarget(17, 42, "abc"))
    running = jobs.claim()
    jobs.complete(running, verdict="fail", exit_code=1)

    response = _call(app, path=f"/reviews/{job.job_id}", headers=_auth())

    assert response.code == 200
    assert response.json["state"] == "succeeded"
    assert response.json["verdict"] == "fail"
    assert response.json["exit_code"] == 1


def test_a_status_never_carries_the_comment():
    """It is rendered from the diff and may quote it. The merge request
    already has it."""
    app, jobs = _api()
    job, _ = jobs.submit(ReviewTarget(17, 42, "abc"))

    response = _call(app, path=f"/reviews/{job.job_id}", headers=_auth())

    assert "comment" not in response.json
    assert not any("diff" in str(key) for key in response.json)


def test_an_unknown_job_is_404():
    app, _ = _api()

    assert _call(app, path="/reviews/nope", headers=_auth()).code == 404


def test_a_status_with_no_id_is_404():
    app, _ = _api()

    assert _call(app, path="/reviews/", headers=_auth()).code == 404


# -- metrics -----------------------------------------------------------------


def test_metrics_returns_openmetrics_text():
    app, _ = _api(metrics=lambda: "# HELP x y\n# TYPE x gauge\nx 1\n")

    response = _call(app, path="/metrics", headers=_auth())

    assert response.code == 200
    assert "text/plain" in response.header("Content-Type")
    assert b"# HELP" in response.body


# -- routing -----------------------------------------------------------------


def test_an_unknown_path_is_404():
    app, _ = _api()

    assert _call(app, path="/nope").code == 404


def test_an_unsupported_method_is_405_with_allow():
    app, _ = _api()

    response = _call(app, method="DELETE", path="/healthz")

    assert response.code == 405
    assert response.header("Allow") == "GET"


def test_a_handler_that_raises_is_500_and_says_nothing_about_why():
    """An error message built from an exception is a way to learn about the
    inside of a process."""
    app, _ = _api(metrics=_explode)

    response = _call(app, path="/metrics", headers=_auth())

    assert response.code == 500
    assert response.json == {"error": "internal error"}


def _explode():
    raise RuntimeError("the collector is on fire and here is its stack")


def test_every_response_carries_a_content_length():
    app, _ = _api()

    response = _call(app, path="/healthz")

    assert response.header("Content-Length") == str(len(response.body))


# -- the webhook -------------------------------------------------------------


def _event(action="open", kind="merge_request", **overrides):
    document = {
        "object_kind": kind,
        "project": {"id": 17},
        "object_attributes": {
            "iid": 42,
            "action": action,
            "last_commit": {"id": "abc123"},
        },
    }
    document.update(overrides)
    return document


def test_a_webhook_with_the_right_token_enqueues_a_review():
    app, jobs = _api()

    response = _call(
        app,
        method="POST",
        path="/webhooks/gitlab",
        body=_event(),
        headers={"X-Gitlab-Token": WEBHOOK_SECRET},
    )

    assert response.code == 202
    job = jobs.get(response.json["id"])
    assert job.target == ReviewTarget(17, 42, "abc123")


def test_a_webhook_with_a_wrong_token_is_401_before_the_body_is_parsed():
    app, _ = _api()
    stream = io.BytesIO(b"{this would raise if parsed")
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/webhooks/gitlab",
        "CONTENT_LENGTH": "26",
        "wsgi.input": stream,
        "HTTP_X_GITLAB_TOKEN": "wrong",
    }
    response = Response()

    def start_response(status, headers):
        response.status = status
        response.headers = list(headers)

    response.body = b"".join(app(environ, start_response))

    assert response.code == 401
    assert stream.tell() == 0


def test_a_webhook_with_no_configured_secret_refuses_everything():
    """An unset secret is a misconfiguration, and defaulting to 'accept' would
    be the worst reading of it."""
    app, _ = _api(webhook_secret="")

    response = _call(
        app,
        method="POST",
        path="/webhooks/gitlab",
        body=_event(),
        headers={"X-Gitlab-Token": ""},
    )

    assert response.code == 401


@pytest.mark.parametrize(
    "document",
    [_event(action="close"), _event(action="merge"), _event(kind="push"), {"object_kind": "note"}],
)
def test_an_event_nobody_asked_for_is_accepted_and_ignored(document):
    """An endpoint that errors on events it does not care about gets disabled
    by whoever is watching the delivery log."""
    app, jobs = _api()

    response = _call(
        app,
        method="POST",
        path="/webhooks/gitlab",
        body=document,
        headers={"X-Gitlab-Token": WEBHOOK_SECRET},
    )

    assert response.code == 204
    assert response.body == b""
    assert not jobs.is_saturated


def test_a_merge_request_event_missing_its_identifiers_is_400():
    app, _ = _api()

    response = _call(
        app,
        method="POST",
        path="/webhooks/gitlab",
        body={"object_kind": "merge_request", "object_attributes": {"action": "open"}},
        headers={"X-Gitlab-Token": WEBHOOK_SECRET},
    )

    assert response.code == 400


def test_a_merge_request_event_with_no_attributes_is_400():
    app, _ = _api()

    response = _call(
        app,
        method="POST",
        path="/webhooks/gitlab",
        body={"object_kind": "merge_request"},
        headers={"X-Gitlab-Token": WEBHOOK_SECRET},
    )

    assert response.code == 400


def test_two_webhooks_for_one_commit_enqueue_one_review():
    app, _ = _api()
    headers = {"X-Gitlab-Token": WEBHOOK_SECRET}

    first = _call(app, method="POST", path="/webhooks/gitlab", body=_event(), headers=headers)
    second = _call(app, method="POST", path="/webhooks/gitlab", body=_event(), headers=headers)

    assert second.code == 200
    assert second.json["id"] == first.json["id"]


def test_a_push_to_the_merge_request_is_a_new_review():
    app, _ = _api()
    headers = {"X-Gitlab-Token": WEBHOOK_SECRET}
    updated = _event(action="update")
    updated["object_attributes"]["last_commit"] = {"id": "def456"}

    first = _call(app, method="POST", path="/webhooks/gitlab", body=_event(), headers=headers)
    second = _call(app, method="POST", path="/webhooks/gitlab", body=updated, headers=headers)

    assert second.code == 202
    assert second.json["id"] != first.json["id"]


def test_the_webhook_route_uses_the_webhook_auth_and_not_the_bearer():
    route = next(route for route in ReviewApi.ROUTES if route.path == "/webhooks/gitlab")

    assert route.auth == WEBHOOK


# -- R-06: a request that carries no Content-Length ---------------------------
#
# `_read_body` reads exactly CONTENT_LENGTH bytes, which is what keeps an
# oversized body costing a header parse rather than a megabyte. A chunked
# request carries no length, so it read nothing and the caller was told its
# body was missing: a true statement about what was read and a misleading one
# about what was sent.


def _call_without_length(app, path="/reviews", headers=None, transfer_encoding=""):
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "wsgi.input": io.BytesIO(b""),
    }
    if transfer_encoding:
        environ["HTTP_TRANSFER_ENCODING"] = transfer_encoding
    for name, value in (headers or {}).items():
        environ[f"HTTP_{name.upper().replace('-', '_')}"] = value

    response = Response()

    def start_response(status, response_headers):
        response.status = status
        response.headers = list(response_headers)

    response.body = b"".join(app(environ, start_response))
    return response


def test_a_chunked_body_is_refused_with_a_reason_that_names_the_cause():
    app, _ = _api()

    response = _call_without_length(app, headers=_auth(), transfer_encoding="chunked")

    assert response.code == 411
    assert "chunked" in response.json["error"]


def test_a_request_with_no_body_at_all_still_says_a_body_is_required():
    app, _ = _api()

    response = _call_without_length(app, headers=_auth())

    assert response.code == 400
    assert "body is required" in response.json["error"]


# -- R-07: the route table compares by value ----------------------------------
#
# `route.auth is OPEN` was true only because the table is built from this
# module's own constants. The day one is computed -- read from a config, joined
# from a string -- an authenticated route silently becomes an open one, which
# is the wrong direction for that failure to go.


def test_a_route_whose_auth_was_computed_behaves_like_the_constant():
    from code_reviewer.infrastructure.http.app import Route

    computed = "".join(list(OPEN))
    assert computed is not OPEN

    class OneRoute(ReviewApi):
        ROUTES = (Route("GET", "/healthz", computed, "_healthz"),)

    _, jobs = _api()

    response = _call(OneRoute(jobs, api_token=TOKEN), path="/healthz")

    assert response.code == 200
