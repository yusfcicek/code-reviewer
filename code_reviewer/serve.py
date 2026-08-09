"""``ai-code-review-serve`` — the same review, behind HTTP.

A third console entry point, for the reason the second one exists: pipelines
invoke `ai-code-review` with a fixed argument list, and a service is not a
subcommand of a job.

What it builds is a WSGI application and one worker thread. The application is
the deployable artefact — `create_app()` is what a gunicorn or uvicorn command
line points at — and the built-in server here is `wsgiref`, which is
single-threaded and adequate for a laptop and for a readiness probe, and is not
what a container should run. Level 19's image will say so in its command.

The service refuses to start without a token. Serving unauthenticated because a
variable was unset is the failure that gets found by somebody else.
"""

import argparse
import atexit
import logging
import os
import signal
import sys
import threading
from collections.abc import Sequence
from wsgiref.simple_server import make_server

from code_reviewer.application.jobs import DEFAULT_QUEUE_DEPTH, InMemoryJobStore, JobService
from code_reviewer.application.review_service import ReviewService
from code_reviewer.cli import _env, _positive
from code_reviewer.errors import ConfigurationError
from code_reviewer.infrastructure.deployment.settings import build_readiness_probe
from code_reviewer.infrastructure.http.app import ReviewApi
from code_reviewer.infrastructure.http.worker import ReviewWorker
from code_reviewer.infrastructure.observability.logging import configure_logging

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIGURATION = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-code-review-serve",
        description="Serve the review agent over HTTP",
    )
    parser.add_argument("--host", type=str, default=_env("REVIEW_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(_env("REVIEW_PORT", "8080")))
    parser.add_argument(
        "--queue-depth",
        type=_positive,
        default=_positive(_env("REVIEW_QUEUE_DEPTH", str(DEFAULT_QUEUE_DEPTH))),
        help="How many reviews may wait before the service answers 429",
    )
    parser.add_argument(
        "--drain-seconds",
        type=float,
        default=float(_env("REVIEW_DRAIN_SECONDS", "25")),
        help=(
            "How long a SIGTERM waits for the review in flight. Below the "
            "orchestrator's grace period, so the drain finishes first or says it did not."
        ),
    )
    parser.add_argument(
        "--log-level", type=str, default=_env("LOG_LEVEL", "INFO"), help="DEBUG, INFO, WARNING, ERROR"
    )
    return parser


def build_application(
    args, review_service: ReviewService | None = None
) -> tuple[ReviewApi, ReviewWorker, JobService]:
    """The application, its worker and the queue between them.

    Args:
        args: Parsed arguments.
        review_service: Injected by a test. Built from the composition root
            otherwise, which is where every adapter this needs already lives.

    Raises:
        ConfigurationError: with no ``REVIEW_API_TOKEN``. Serving
            unauthenticated because a variable was unset is the failure that
            gets found by somebody else.
    """
    token = os.getenv("REVIEW_API_TOKEN", "").strip()
    if not token:
        raise ConfigurationError(
            "REVIEW_API_TOKEN is not set. The service will not start without one: "
            "an unauthenticated review endpoint can read any repository this process can."
        )

    webhook_secret = os.getenv("GITLAB_WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        # Not fatal: a deployment may want the API without the webhook. The
        # endpoint itself then refuses everything, which is the safe reading.
        logger.warning("GITLAB_WEBHOOK_SECRET is not set; the webhook will refuse every request")

    jobs = JobService(InMemoryJobStore(), max_queue_depth=args.queue_depth)
    reviews = review_service if review_service is not None else _build_review_service()

    application = ReviewApi(
        jobs,
        api_token=token,
        webhook_secret=webhook_secret,
        # Real checks since Level 19. A container wired to a probe that always
        # passes is worse than one with no probe: Kubernetes routes to it while
        # it is unconfigured.
        ready=build_readiness_probe().as_probe(),
    )
    return application, ReviewWorker(jobs, reviews), jobs


def create_app():
    """The WSGI callable a production server points at.

    Starts the worker as a side effect, because a server that imports this
    module and serves the application is a server that also needs something
    draining the queue.

    The drain is registered with `atexit` rather than on a signal. Under
    gunicorn the signals belong to gunicorn — installing a handler here would
    take SIGTERM away from the thing that knows how to stop serving requests —
    and a worker exiting on SIGTERM raises `SystemExit`, which runs the exit
    handlers. Without this the review in flight died with the interpreter: the
    worker thread is a daemon, and `main()`'s drain is on the entry point
    nobody deploys (self-review R-01).
    """
    args = build_parser().parse_args([])
    application, worker, _ = build_application(args)
    worker.start()
    atexit.register(lambda: drain(worker, args.drain_seconds))
    return application


def install_signal_handlers(server) -> None:
    """Turns SIGTERM and SIGINT into an orderly stop.

    `serve_forever` blocks the main thread and `shutdown` waits for that loop
    to notice, so calling it from a handler that *runs on* the main thread
    deadlocks. The handler starts a thread whose only job is to ask.
    """

    def handle(signum, _frame):
        logger.info("Signal received; draining", extra={"fields": {"signal": signum}})
        threading.Thread(target=server.shutdown, name="shutdown", daemon=True).start()

    for received in (signal.SIGTERM, signal.SIGINT):
        signal.signal(received, handle)


def drain(worker: ReviewWorker, seconds: float) -> int:
    """Lets the review in flight finish, within a bound.

    Says which of "finished" and "gave up" happened. A shutdown that waits
    forever is a pod that gets SIGKILLed anyway, with the same review half-run
    and nothing in the log about it (decision D-5).
    """
    if worker.stop(timeout=seconds):
        logger.info("Drained cleanly")
    else:
        logger.warning(
            "The review in flight did not finish; exiting anyway",
            extra={"fields": {"waited_seconds": seconds}},
        )
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    configure_logging(args.log_level)

    try:
        application, worker, _ = build_application(args)
    except ConfigurationError as error:
        print(f"Cannot start: {error}", file=sys.stderr)  # stdout: the program's output
        return EXIT_CONFIGURATION

    worker.start()
    server = make_server(args.host, args.port, application)
    install_signal_handlers(server)
    logger.info("Serving", extra={"fields": {"host": args.host, "port": args.port}})

    try:
        server.serve_forever()
    finally:
        server.server_close()

    return drain(worker, args.drain_seconds)


def _build_review_service() -> ReviewService:
    """The review, assembled exactly the way the command line assembles it.

    The review parser's defaults, not this one's: the service and the job are
    the same review, and two ways of building it would drift.
    """
    from code_reviewer.__main__ import build_review_service
    from code_reviewer.cli import build_parser as review_parser

    service, _ = build_review_service(review_parser().parse_args([]))
    return service


if __name__ == "__main__":  # pragma: no cover - exercised through the entry point
    raise SystemExit(main())
