"""Command-line interface definition.

Separated from the orchestration so argument handling can be tested without
touching GitLab or a model.

``--project-id`` and ``--mr-iid`` used to be declared ``type=int`` with
``default=os.getenv(...)``. argparse converts command-line strings with ``type``
but leaves defaults untouched, so under CI the same program carried strings
where it expected integers (finding F-15). Environment defaults are now
converted through the same code path as the command line, and a non-numeric
value is rejected with a message instead of surfacing later as a type surprise.
"""

import argparse
import os
import sys
from collections.abc import Sequence

#: Where GitLab CI picks up the metrics report artifact.
DEFAULT_METRICS_PATH = "metrics.txt"


def _env_int(name: str) -> str | None:
    """Reads an environment default, leaving conversion to argparse's ``type``."""
    value = os.getenv(name)
    return value if value not in (None, "") else None


def _env(name: str, fallback: str) -> str:
    """An environment default for a plain string option.

    Each operational flag has one, so a pipeline sets it once in its variables
    block rather than on every invocation.
    """
    value = os.getenv(name)
    return value if value else fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-code-review",
        description="Autonomous Enterprise Code Review Agent",
    )
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help="GitLab Project ID (defaults to $CI_PROJECT_ID)",
    )
    parser.add_argument(
        "--mr-iid",
        type=int,
        default=None,
        help="Merge Request IID (defaults to $CI_MERGE_REQUEST_IID)",
    )
    parser.add_argument(
        "--policy",
        type=str,
        default=None,
        help="Path to a policy YAML file (defaults to the bundled review_policy.yaml)",
    )
    parser.add_argument(
        "--repo-root",
        type=str,
        default=_env("CI_PROJECT_DIR", "."),
        help="Workspace root. The agent cannot read outside this directory.",
    )
    parser.add_argument(
        "--metrics-path",
        type=str,
        default=_env("REVIEW_METRICS_PATH", DEFAULT_METRICS_PATH),
        help=f"Where to write the OpenMetrics report (default: {DEFAULT_METRICS_PATH})",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=_env("LOG_LEVEL", "INFO"),
        help="DEBUG, INFO (default), WARNING or ERROR",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the report instead of posting it. The exit code is still the "
            "real one, so a dry run answers 'would this block the merge'."
        ),
    )
    parser.add_argument(
        "--memory-path",
        type=str,
        default=_env("REVIEW_MEMORY_PATH", ""),
        help=(
            "Where this project's review history is kept. Defaults to "
            ".review-memory.json inside the workspace."
        ),
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help=(
            "Review without the project's history, and record nothing. The "
            "verdict is unchanged either way: memory informs, it never decides."
        ),
    )
    parser.add_argument(
        "--single-agent",
        action="store_true",
        help=(
            "Review with one agent instead of the committee of specialists. "
            "Fewer model calls per file, and the behaviour of every level before 15."
        ),
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help=(
            "Run static analysis only, with no model endpoint. The verdict is "
            "unchanged: it has never come from the model."
        ),
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parses ``argv``, filling missing identifiers from the CI environment.

    Environment values go through the parser rather than around it, so
    ``CI_PROJECT_ID=abc`` fails immediately and with the same message a bad
    command-line value would produce.
    """
    parser = build_parser()
    argv = list(argv if argv is not None else sys.argv[1:])
    args = parser.parse_args(argv)

    # Append the CI values as if they had been typed on the command line, so
    # argparse applies `type=int` to them through exactly the same code path.
    extra = []
    for attribute, flag, variable in (
        ("project_id", "--project-id", "CI_PROJECT_ID"),
        ("mr_iid", "--mr-iid", "CI_MERGE_REQUEST_IID"),
    ):
        raw = _env_int(variable)
        if getattr(args, attribute) is None and raw is not None:
            extra.extend([flag, raw])

    return parser.parse_args(argv + extra) if extra else args
