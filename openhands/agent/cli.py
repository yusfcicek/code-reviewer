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
from typing import Optional, Sequence


def _env_int(name: str) -> Optional[str]:
    """Reads an environment default, leaving conversion to argparse's ``type``."""
    value = os.getenv(name)
    return value if value not in (None, "") else None


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
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
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
