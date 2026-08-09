"""The service surface, as a WSGI application.

FastAPI is the industry answer and this is not it. It would bring starlette,
pydantic, anyio and a dozen transitive packages into a process whose dependency
audit runs with an empty ignore list, to serve six endpoints whose bodies have
two fields each. WSGI is the standard interface every Python server speaks: the
same object runs under gunicorn, uvicorn or `wsgiref` unchanged, and it is
tested by calling it with a dictionary — no client, no event loop, no test
server (decision D-1).

What that costs is stated rather than hidden: no generated OpenAPI schema, and
validation written by hand. Both are small at six endpoints and would not stay
small at sixty, which is the point at which this decision should be revisited.

The application is *one adapter*. It calls `JobService` and nothing else — no
gate logic, no policy, no report rendering. A gRPC surface would be a sibling
module against the same objects.
"""

import hmac
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from code_reviewer.application.jobs import JobService, QueueFull
from code_reviewer.domain.job import ReviewTarget

from .gitlab_events import EventError, read_merge_request_event

logger = logging.getLogger(__name__)

#: Largest request body accepted. A webhook payload comes from outside, and the
#: rule Level 8 applied to a diff applies to a payload.
MAX_BODY_BYTES = 1_000_000

#: How long a caller is asked to wait when the queue is full.
RETRY_AFTER_SECONDS = 30

OPEN = "open"
BEARER = "bearer"
WEBHOOK = "webhook"


@dataclass(frozen=True)
class Route:
    """One endpoint, and what it takes to reach it."""

    method: str
    path: str
    auth: str
    handler: str
    #: True when ``path`` is a prefix and the remainder is an identifier.
    parameterised: bool = False


class ReviewApi:
    """The HTTP surface. A WSGI callable.

    Args:
        jobs: Where a review is accepted and read back.
        api_token: The bearer token every authenticated route requires.
        webhook_secret: Compared against ``X-Gitlab-Token``. Empty means the
            webhook refuses everything: an unset secret is a misconfiguration,
            and defaulting to "accept" would be the worst reading of it.
        metrics: Returns the OpenMetrics text.
        ready: Returns ``(ready, reason)``.
    """

    #: Every route, in one table, so a test can assert over it rather than one
    #: route at a time — which is what makes a route added later covered by
    #: construction rather than by somebody remembering.
    ROUTES: tuple[Route, ...] = (
        Route("GET", "/healthz", OPEN, "_healthz"),
        Route("GET", "/readyz", OPEN, "_readyz"),
        Route("GET", "/metrics", BEARER, "_metrics_endpoint"),
        Route("POST", "/reviews", BEARER, "_submit_review"),
        Route("GET", "/reviews/", BEARER, "_review_status", parameterised=True),
        Route("POST", "/webhooks/gitlab", WEBHOOK, "_gitlab_webhook"),
    )

    def __init__(
        self,
        jobs: JobService,
        api_token: str,
        webhook_secret: str = "",
        metrics: Callable[[], str] | None = None,
        ready: Callable[[], tuple[bool, str]] | None = None,
    ):
        self._jobs = jobs
        self._api_token = api_token
        self._webhook_secret = webhook_secret
        self._metrics = metrics or (lambda: "")
        self._ready = ready or (lambda: (True, "ready"))

    # -- WSGI ---------------------------------------------------------------

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/") or "/"

        route = self._match(method, path)
        if route is None:
            return self._respond(start_response, *self._unmatched(method, path))

        refusal = self._authorise(route, environ)
        if refusal is not None:
            return self._respond(start_response, *refusal)

        try:
            status, headers, body = getattr(self, route.handler)(environ, path)
        except Exception:
            # Nothing about the failure reaches the caller. An error message
            # built from an exception is a way to learn about the inside of a
            # process, and the log already has the whole thing.
            logger.exception("Unhandled error serving %s %s", method, path)
            status, headers, body = _json(500, {"error": "internal error"})

        return self._respond(start_response, status, headers, body)

    # -- routing ------------------------------------------------------------

    def _match(self, method: str, path: str) -> Route | None:
        for route in self.ROUTES:
            matches = path.startswith(route.path) if route.parameterised else path == route.path
            if matches and route.method == method:
                return route
        return None

    def _unmatched(self, method: str, path: str):
        """404 for a path nobody serves, 405 for a method nobody accepts."""
        allowed = sorted(
            {
                route.method
                for route in self.ROUTES
                if (path.startswith(route.path) if route.parameterised else path == route.path)
            }
        )
        if allowed:
            status, headers, body = _json(405, {"error": f"{method} is not allowed here"})
            return status, [*headers, ("Allow", ", ".join(allowed))], body
        return _json(404, {"error": "no such endpoint"})

    def _authorise(self, route: Route, environ: dict[str, Any]):
        """``None`` when the request may proceed, else the refusal."""
        if route.auth is OPEN:
            return None

        if route.auth is BEARER:
            header = environ.get("HTTP_AUTHORIZATION", "")
            scheme, _, presented = header.partition(" ")
            if scheme.lower() != "bearer" or not _matches(presented, self._api_token):
                return _json(401, {"error": "unauthorized"})
            return None

        presented = environ.get("HTTP_X_GITLAB_TOKEN", "")
        if not _matches(presented, self._webhook_secret):
            # Refused before the body is read, so an unverified payload is
            # never parsed (contract C-6).
            return _json(401, {"error": "unauthorized"})
        return None

    @staticmethod
    def _respond(start_response: Callable, status: str, headers: list, body: bytes):
        start_response(status, [*headers, ("Content-Length", str(len(body)))])
        return [body]

    # -- handlers -----------------------------------------------------------

    def _healthz(self, environ, path):
        """This process is running. Nothing more is claimed."""
        return _json(200, {"status": "alive"})

    def _readyz(self, environ, path):
        """This process can accept work.

        Deliberately no call to GitLab: a readiness probe that depends on a
        third party takes the deployment down when the third party is slow,
        which is exactly when it is most needed (decision D-5).
        """
        if self._jobs.is_saturated:
            return _json(503, {"status": "saturated", "reason": "the review queue is full"})

        ready, reason = self._ready()
        return _json(200 if ready else 503, {"status": "ready" if ready else "not ready", "reason": reason})

    def _metrics_endpoint(self, environ, path):
        """Named for the route rather than for the field.

        `getattr(self, route.handler)` resolves against the instance, and a
        handler called `_metrics` would have returned the *collector* stored
        under the same name rather than the method. The test that submitted a
        zero-argument collector found it, which is what a route table tested as
        a table is for.
        """
        return (
            "200 OK",
            [("Content-Type", "text/plain; version=0.0.4; charset=utf-8")],
            self._metrics().encode("utf-8"),
        )

    def _submit_review(self, environ, path):
        body, error = _read_body(environ)
        if error is not None:
            return error

        document, error = _parse_json(body)
        if error is not None:
            return error

        target, reason = _read_target(document)
        if target is None:
            return _json(400, {"error": reason})

        key = str(document.get("idempotency_key") or environ.get("HTTP_IDEMPOTENCY_KEY", "") or "")

        try:
            job, created = self._jobs.submit(target, idempotency_key=key)
        except QueueFull as full:
            return (
                "429 Too Many Requests",
                [
                    ("Content-Type", "application/json"),
                    ("Retry-After", str(RETRY_AFTER_SECONDS)),
                ],
                json.dumps({"error": str(full)}).encode("utf-8"),
            )

        status, headers, payload = _json(202 if created else 200, _job_summary(job))
        return status, [*headers, ("Location", f"/reviews/{job.job_id}")], payload

    def _review_status(self, environ, path):
        job_id = path[len("/reviews/") :].strip("/")
        job = self._jobs.get(job_id) if job_id else None
        if job is None:
            return _json(404, {"error": "no such review"})
        return _json(200, _job_summary(job))

    def _gitlab_webhook(self, environ, path):
        body, error = _read_body(environ)
        if error is not None:
            return error

        document, error = _parse_json(body)
        if error is not None:
            return error

        try:
            target = read_merge_request_event(document)
        except EventError as problem:
            return _json(400, {"error": str(problem)})

        if target is None:
            # Accepted and ignored. An endpoint that errors on events it does
            # not care about gets disabled by whoever watches the delivery log.
            return "204 No Content", [("Content-Type", "application/json")], b""

        try:
            job, created = self._jobs.submit(target)
        except QueueFull as full:
            return (
                "429 Too Many Requests",
                [("Content-Type", "application/json"), ("Retry-After", str(RETRY_AFTER_SECONDS))],
                json.dumps({"error": str(full)}).encode("utf-8"),
            )

        return _json(202 if created else 200, _job_summary(job))


# -- helpers -----------------------------------------------------------------


def _matches(presented: str, expected: str) -> bool:
    """Constant-time comparison that refuses an unset expectation.

    An empty configured secret means "nobody may in", not "everybody may":
    a service that authenticates against the empty string is a service with no
    authentication and a login page.
    """
    if not expected or not presented:
        return False
    return hmac.compare_digest(presented, expected)


def _read_body(environ: dict[str, Any]) -> tuple[bytes, Any]:
    """The request body, or a refusal.

    The length is checked before anything is read, so an oversized body costs
    a header parse rather than a megabyte of memory.
    """
    raw_length = environ.get("CONTENT_LENGTH", "") or "0"
    try:
        length = int(raw_length)
    except ValueError:
        return b"", _json(400, {"error": "Content-Length is not a number"})

    if length > MAX_BODY_BYTES:
        return b"", _json(413, {"error": f"a body may not exceed {MAX_BODY_BYTES} bytes"})
    if length <= 0:
        return b"", None

    stream = environ.get("wsgi.input")
    return (stream.read(length) if stream is not None else b""), None


def _parse_json(body: bytes) -> tuple[dict[str, Any], Any]:
    if not body:
        return {}, _json(400, {"error": "a body is required"})
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}, _json(400, {"error": "the body is not valid JSON"})
    if not isinstance(document, dict):
        return {}, _json(400, {"error": "the body must be a JSON object"})
    return document, None


def _read_target(document: dict[str, Any]) -> tuple[ReviewTarget | None, str]:
    """The review this request is asking for, or why it is not one."""
    for field in ("project_id", "merge_request_iid"):
        value = document.get(field)
        if value is None:
            return None, f"'{field}' is required"
        if isinstance(value, bool) or not isinstance(value, int):
            return None, f"'{field}' must be a whole number"

    head_sha = document.get("head_sha", "")
    if not isinstance(head_sha, str):
        return None, "'head_sha' must be a string"

    return (
        ReviewTarget(
            project_id=int(document["project_id"]),
            merge_request_iid=int(document["merge_request_iid"]),
            head_sha=head_sha,
        ),
        "",
    )


def _job_summary(job) -> dict[str, Any]:
    """What a caller is told about a job.

    Not the comment. It is rendered from the diff and may quote it, so an
    endpoint that returns it is a second way to get source out of the process —
    and the merge request already has it (decision D-4).
    """
    return {
        "id": job.job_id,
        "state": job.state.value,
        "project_id": job.target.project_id,
        "merge_request_iid": job.target.merge_request_iid,
        "head_sha": job.target.head_sha,
        "verdict": job.verdict or None,
        "exit_code": job.exit_code,
        "failure_reason": job.failure_reason or None,
        "trace_id": job.trace_id or None,
        "submitted_at": job.submitted_at.isoformat() if job.submitted_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


_STATUS_TEXT = {
    200: "200 OK",
    202: "202 Accepted",
    204: "204 No Content",
    400: "400 Bad Request",
    401: "401 Unauthorized",
    404: "404 Not Found",
    405: "405 Method Not Allowed",
    413: "413 Payload Too Large",
    500: "500 Internal Server Error",
    503: "503 Service Unavailable",
}


def _json(code: int, payload: dict[str, Any]):
    return (
        _STATUS_TEXT[code],
        [("Content-Type", "application/json")],
        json.dumps(payload).encode("utf-8"),
    )
