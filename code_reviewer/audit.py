"""``ai-code-review-audit`` — check that the decision records were not altered.

A fourth console entry point, for the reason the third and second exist: a
pipeline invokes `ai-code-review` with a fixed argument list, and moving a new
verb behind a subcommand of it would break every one of them (decision D-5).

Three exit codes, the split Level 10 introduced:

* ``0`` — the store is intact.
* ``1`` — something in it does not add up, at a stated position.
* ``2`` — the question could not be answered: the file is not there, or the
  records are signed and no key was given to check them.

The third is the one worth insisting on. A missing store and a tampered store
are different facts, and so are "the signature is wrong" and "there is no key
here". Conflating them makes the command unusable in a pipeline, which then
treats every answer as advice.

Nothing this command prints comes from a record. Whoever is allowed to run a
verifier is not necessarily allowed to read the merge requests it covers, and a
report that quotes a project name to explain a broken link has published
something to whoever reads the log.
"""

import argparse
import os
import sys
from collections.abc import Sequence

from code_reviewer.domain.audit import ChainStatus
from code_reviewer.infrastructure.governance.sealed_sink import status_line, verify_store
from code_reviewer.infrastructure.governance.signing import signer_from_environment

#: The store is sound.
EXIT_INTACT = 0
#: The store is not.
EXIT_TAMPERED = 1
#: The question could not be answered.
EXIT_CANNOT_VERIFY = 2

#: Where the records are, when the command is not told.
PATH_VARIABLE = "REVIEW_AUDIT_PATH"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-code-review-audit",
        description="Check that a decision-record store has not been altered.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    verify = subcommands.add_parser("verify", help="Check a store end to end.")
    verify.add_argument(
        "--path",
        default=os.environ.get(PATH_VARIABLE, ""),
        help=(
            "The newline-delimited store to check. Defaults to "
            f"${PATH_VARIABLE}; with neither, there is nothing to verify."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    return _verify(args)


def _verify(args) -> int:
    if not args.path:
        print(  # stdout: the program's output, not a diagnostic
            f"Nothing to verify: no --path and no ${PATH_VARIABLE}.", file=sys.stderr
        )
        return EXIT_CANNOT_VERIFY

    if not os.path.isfile(args.path):
        # Distinguished from a tamper on purpose: a store that is not there is
        # a deployment fact, and reporting it as an attack is how an operator
        # learns to ignore this command.
        print(f"Nothing to verify: '{args.path}' is not a file.", file=sys.stderr)  # stdout: the output
        return EXIT_CANNOT_VERIFY

    verdict = verify_store(args.path, signer_from_environment())
    print(status_line(verdict))  # stdout: the program's output, not a diagnostic

    if verdict.status is ChainStatus.INTACT:
        return EXIT_INTACT
    if verdict.status is ChainStatus.UNVERIFIABLE:
        return EXIT_CANNOT_VERIFY
    return EXIT_TAMPERED


if __name__ == "__main__":  # pragma: no cover - exercised through the entry point
    raise SystemExit(main())
