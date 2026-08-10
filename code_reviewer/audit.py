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
from datetime import UTC, datetime

from code_reviewer.application.erasure import erase, redact
from code_reviewer.domain.audit import ChainStatus
from code_reviewer.infrastructure.governance.sealed_sink import FileAuditStore, status_line, verify_store
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
        "--expect-at-least",
        type=int,
        default=0,
        help=(
            "How many records an anchor OUTSIDE this file says the store should "
            "hold. Truncation is not detectable from the file alone — a prefix "
            "of a valid chain is a valid chain — so this is the only way to "
            "catch it, and it needs a number you kept elsewhere."
        ),
    )
    verify.add_argument(
        "--path",
        default=os.environ.get(PATH_VARIABLE, ""),
        help=(
            "The newline-delimited store to check. Defaults to "
            f"${PATH_VARIABLE}; with neither, there is nothing to verify."
        ),
    )
    erase_command = subcommands.add_parser(
        "erase",
        help="Replace matching records with tombstones and re-seal the store.",
        description=(
            "Removes records deliberately. The chain is rewritten and re-signed so "
            "the store still verifies, and each removed position keeps a tombstone "
            "naming when and under which policy — erasure and tampering stay "
            "distinguishable. A store that does not already verify is refused: "
            "rewriting it would re-seal somebody else's alteration."
        ),
    )
    _store_arguments(erase_command)
    erase_command.add_argument(
        "--before", default="", help="Remove records recorded before this ISO timestamp."
    )
    erase_command.add_argument("--project", default="", help="Remove records of this project.")
    erase_command.add_argument("--merge-request", default="", help="Remove records of this merge request.")

    redact_command = subcommands.add_parser(
        "redact",
        help="Empty the fields naming a subject, keeping the rest of the record.",
        description=(
            "The weaker operation, and often the right one: the organisation can "
            "still say a review happened, and only the identifiers go."
        ),
    )
    _store_arguments(redact_command)
    redact_command.add_argument("--project", default="", help="Redact records of this project.")
    redact_command.add_argument("--merge-request", default="", help="Redact records of this merge request.")

    return parser


def _store_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--path",
        default=os.environ.get(PATH_VARIABLE, ""),
        help=f"The store to rewrite. Defaults to ${PATH_VARIABLE}.",
    )
    command.add_argument(
        "--policy",
        required=True,
        help=(
            "What this is being done under. Written into every tombstone, "
            "because 'why is this position empty' is the first question "
            "anybody asks about one."
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    if args.command == "verify":
        return _verify(args)
    return _rewrite(args)


def _rewrite(args) -> int:
    """Erasure and redaction. Exits `2` when the store refused the operation.

    Refusing is not a failure of the store — it is this command declining to
    produce something worse than what it was asked to change — so it lands on
    the "could not do it" code rather than on "the store is wrong".
    """
    if not args.path:
        print(f"Nothing to change: no --path and no ${PATH_VARIABLE}.", file=sys.stderr)  # stdout: output
        return EXIT_CANNOT_VERIFY

    store = FileAuditStore(args.path)
    signer = signer_from_environment()
    now = datetime.now(UTC).isoformat()

    if args.command == "erase":
        outcome = erase(
            store,
            policy=args.policy,
            now=now,
            before=args.before,
            project=args.project,
            merge_request=args.merge_request,
            signer=signer,
        )
    else:
        outcome = redact(
            store,
            policy=args.policy,
            now=now,
            project=args.project,
            merge_request=args.merge_request,
            signer=signer,
        )

    if outcome.refused:
        print(f"Refused: {outcome.refused}", file=sys.stderr)  # stdout: the program's output
        return EXIT_CANNOT_VERIFY

    print(  # stdout: the program's output, not a diagnostic
        f"{outcome.removed} removed, {outcome.redacted} redacted, {outcome.kept} kept."
    )
    return EXIT_INTACT


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

    signer = signer_from_environment()
    verdict = verify_store(args.path, signer, expect_at_least=args.expect_at_least)
    print(status_line(verdict))  # stdout: the program's output, not a diagnostic
    if verdict.status is ChainStatus.UNVERIFIABLE and signer.key_ids:
        # Both halves of the comparison, because the mistake this is for is a
        # name that does not match: a retired key configured as `2025-KEY`
        # against records that wrote `2025-key` (Level 30).
        print(  # stdout: the program's output, not a diagnostic
            f"  Keys held: {', '.join(signer.key_ids)}."
        )

    if verdict.status is ChainStatus.INTACT:
        return EXIT_INTACT
    if verdict.status is ChainStatus.UNVERIFIABLE:
        return EXIT_CANNOT_VERIFY
    return EXIT_TAMPERED


if __name__ == "__main__":  # pragma: no cover - exercised through the entry point
    raise SystemExit(main())
