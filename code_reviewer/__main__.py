"""Composition root.

Builds the adapters, hands them to :class:`ReviewService` and exits with the
code the review implies. All the decisions live in the layers below; this
module only wires them together, which is why it is the one place allowed to
import from every layer.

Usage:
    ai-code-review --project-id <ID> --mr-iid <IID> [options]
"""

import sys
import warnings

from code_reviewer.application.ports import Reviewer
from code_reviewer.application.review_service import ReviewService
from code_reviewer.cli import parse_args
from code_reviewer.domain.triage import ReviewTriage
from code_reviewer.errors import ConfigurationError, ReviewError
from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite
from code_reviewer.infrastructure.config.loader import load_policy
from code_reviewer.infrastructure.forge.gitlab_forge import GitLabForge
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from code_reviewer.infrastructure.llm.vllm import LLMFactory
from code_reviewer.infrastructure.memory.smart_memory import SmartMemoryStrategy
from code_reviewer.infrastructure.metrics.collector import MetricsCollector, ReviewMetrics
from code_reviewer.infrastructure.observability.logging import configure_logging, get_logger
from code_reviewer.infrastructure.retrieval.corpus import build_retriever
from code_reviewer.infrastructure.tools import Workspace, set_retriever, set_workspace

#: Exit codes. The split exists because "the gate blocked the merge request"
#: and "the agent fell over" both used to be `1`, so no pipeline could tell
#: them apart — and that is the distinction someone needs before they will set
#: `allow_failure: false` (finding G-13).
#:
#: `1` is a *successful* run with a negative verdict. `3` is a run that did
#: not happen.
EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_CONFIG_ERROR = 2
EXIT_RUNTIME_ERROR = 3

logger = get_logger(__name__)


def _quieten_dependencies() -> None:
    """Keeps third-party chatter out of the CI log."""
    import logging

    for name in ("tiktoken", "langchain", "openai", "httpx"):
        logging.getLogger(name).setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=".*model not found.*")


class _NoNarration(Reviewer):
    """A reviewer that produces no prose, for `--no-llm`.

    A null object rather than a `None` check inside `ReviewService`: the
    workflow should not learn that a reviewer is optional. The verdict is
    unaffected either way, because it comes from the analyzers
    (ADR 0004) — so this is not a degraded mode, it is the same decision with
    a shorter report.
    """

    def review_diff(
        self, filename, diff_content, full_file_content=None, other_files=None, related=None
    ) -> str:
        return (
            "_Narration was not requested (`--no-llm`). The verdict below comes "
            "from static analysis, which is where it always comes from._"
        )


def _export_metrics(result, project_id, merge_request_iid, metrics_path: str) -> None:
    """Translates the workflow's facts into the exporter's format."""
    collector = MetricsCollector()
    for metric in result.metrics:
        collector.record(
            ReviewMetrics(
                project_id=str(project_id),
                mr_id=str(merge_request_iid),
                file_path=metric.file_path,
                lines_analyzed=metric.lines_analyzed,
                triage_decisions=metric.triage_decisions,
                gate_result=metric.gate_result,
                quality_score=metric.quality_score,
                findings_by_severity=metric.findings_by_severity,
                duration_ms=metric.duration_ms,
            )
        )
    collector.export_gitlab_metrics(metrics_path)


def run(args) -> int:
    """Builds the workflow for one run and returns its exit code."""
    logger.info(
        "Starting review",
        extra={"fields": {"project": args.project_id, "merge_request": args.mr_iid}},
    )

    policy = load_policy(args.policy)
    logger.info("Policy in effect", extra={"fields": {"version": policy.version}})

    # Every file the agent can read is confined to the checkout it is
    # reviewing; the paths it asks for come from the diff (finding F-21).
    workspace = Workspace.from_environment(args.repo_root)
    set_workspace(workspace)
    logger.info(
        "Tools confined",
        extra={
            "fields": {
                "workspace": str(workspace.root),
                "read_budget_bytes": workspace.total_read_budget_bytes,
            }
        },
    )

    # Retrieval over the checkout. Built once per run, from the same tree the
    # tools are confined to, and best-effort throughout: an index that cannot
    # be built costs the prompt its context and nothing else (Level 13, D-5).
    retriever = _build_retriever(args.repo_root)
    set_retriever(retriever)

    service = ReviewService(
        forge=GitLabForge(),
        reviewer=_build_reviewer(args),
        triage=ReviewTriage(policy),
        policy=policy,
        analysis=StaticAnalysisSuite(policy),
        # The workspace records what it refused. A refused read is evidence
        # about the diff — the agent asked for that path because the content
        # under review led it to — so it reaches the gate as a finding.
        access_auditor=workspace,
        retriever=retriever,
    )

    result = service.review(args.project_id, args.mr_iid, publish=not args.dry_run)

    if result.comment and args.dry_run:
        # Printed rather than posted. The exit code is still the real one: a
        # dry run answers "what would this do", and that includes "would it
        # stop the merge" (decision D-3).
        print(result.comment)  # stdout: the program's output, not a diagnostic
        logger.info("Dry run: the report above was not posted")
    elif result.comment:
        logger.info(
            "Review posted",
            extra={"fields": {"files": len(result.metrics), "findings": len(result.findings)}},
        )
    else:
        logger.info("Nothing to review; no comment posted")

    _export_metrics(result, args.project_id, args.mr_iid, args.metrics_path)
    logger.info("Metrics exported", extra={"fields": {"path": args.metrics_path}})

    if result.outcome.is_blocking:
        for issue in result.outcome.blocking_issues:
            logger.error("Blocking issue", extra={"fields": {"issue": issue}})
        if not result.exit_code:
            logger.warning("Policy does not fail the pipeline on blocking issues")

    return result.exit_code


def _build_reviewer(args) -> Reviewer:
    """The narrator, or a stand-in that produces none.

    Constructing the provider is deferred to here so that `--no-llm` needs no
    model endpoint at all — not merely an unused one.
    """
    if args.no_llm:
        logger.info("Running without a model; the verdict comes from static analysis either way")
        return _NoNarration()

    provider = LLMFactory.create_provider("vllm")
    return ReviewAgent(provider, SmartMemoryStrategy(provider))


def _build_retriever(repo_root: str):
    """The repository index, or ``None`` when it could not be built.

    Failing here would trade a whole review for some missing context, which is
    the wrong trade: this project reviewed merge requests for twelve levels
    without retrieving anything.
    """
    try:
        retriever = build_retriever(repo_root)
    except Exception as exc:
        logger.warning(
            "Could not index the repository; reviewing without retrieval",
            extra={"fields": {"repo_root": repo_root, "error": str(exc)}},
        )
        return None

    logger.info("Repository indexed for retrieval", extra={"fields": {"repo_root": repo_root}})
    return retriever


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)
    _quieten_dependencies()

    if not args.project_id or not args.mr_iid:
        logger.error(
            "Missing project ID or merge request IID. Pass --project-id/--mr-iid "
            "or set CI_PROJECT_ID/CI_MERGE_REQUEST_IID."
        )
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        sys.exit(run(args))
    except ConfigurationError as exc:
        # Nothing was reviewed and nothing will be until someone changes the
        # configuration, so retrying is pointless and the code says so.
        logger.error("Configuration error", extra={"fields": {"error": str(exc)}})
        sys.exit(EXIT_CONFIG_ERROR)
    except ReviewError as exc:
        logger.error("Review failed", extra={"fields": {"error": str(exc)}}, exc_info=True)
        sys.exit(EXIT_RUNTIME_ERROR)
    except Exception as exc:
        # Deliberately not EXIT_BLOCKED. A crash reported as a verdict is the
        # defect this taxonomy exists to remove (finding G-13).
        logger.critical("Review run failed", extra={"fields": {"error": str(exc)}}, exc_info=True)
        sys.exit(EXIT_RUNTIME_ERROR)
    except BaseException as exc:
        # KeyboardInterrupt and SystemExit from below are not verdicts either.
        if isinstance(exc, SystemExit):
            raise
        logger.critical("Review run interrupted", extra={"fields": {"error": repr(exc)}})
        sys.exit(EXIT_RUNTIME_ERROR)


if __name__ == "__main__":
    main()
