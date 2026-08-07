"""Composition root.

Builds the adapters, hands them to :class:`ReviewService` and exits with the
code the review implies. All the decisions live in the layers below; this
module only wires them together, which is why it is the one place allowed to
import from every layer.

Usage:
    ai-code-review --project-id <ID> --mr-iid <IID> [--policy <path>]
"""

import sys
import warnings

from code_reviewer.application.review_service import ReviewService
from code_reviewer.cli import parse_args
from code_reviewer.domain.triage import ReviewTriage
from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite
from code_reviewer.infrastructure.config.loader import load_policy
from code_reviewer.infrastructure.forge.gitlab_client import MissingCredentialsError
from code_reviewer.infrastructure.forge.gitlab_forge import GitLabForge
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from code_reviewer.infrastructure.llm.vllm import LLMFactory
from code_reviewer.infrastructure.memory.smart_memory import SmartMemoryStrategy
from code_reviewer.infrastructure.metrics.collector import MetricsCollector, ReviewMetrics
from code_reviewer.infrastructure.observability.logging import configure_logging, get_logger
from code_reviewer.infrastructure.tools import Workspace, set_workspace

#: Where GitLab CI picks up the metrics report artifact.
METRICS_PATH = "metrics.txt"

logger = get_logger(__name__)


def _quieten_dependencies() -> None:
    """Keeps third-party chatter out of the CI log."""
    import logging

    for name in ("tiktoken", "langchain", "openai", "httpx"):
        logging.getLogger(name).setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=".*model not found.*")


def _export_metrics(result, project_id, merge_request_iid) -> None:
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
    collector.export_gitlab_metrics(METRICS_PATH)


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
    workspace = Workspace()
    set_workspace(workspace)
    logger.info("Tools confined", extra={"fields": {"workspace": str(workspace.root)}})

    provider = LLMFactory.create_provider("vllm")
    memory = SmartMemoryStrategy(provider)

    service = ReviewService(
        forge=GitLabForge(),
        reviewer=ReviewAgent(provider, memory),
        triage=ReviewTriage(policy),
        policy=policy,
        analysis=StaticAnalysisSuite(policy),
    )

    result = service.review(args.project_id, args.mr_iid)

    if result.comment:
        logger.info(
            "Review posted",
            extra={"fields": {"files": len(result.metrics), "findings": len(result.findings)}},
        )
    else:
        logger.info("Nothing to review; no comment posted")

    _export_metrics(result, args.project_id, args.mr_iid)
    logger.info("Metrics exported", extra={"fields": {"path": METRICS_PATH}})

    if result.outcome.is_blocking:
        for issue in result.outcome.blocking_issues:
            logger.error("Blocking issue", extra={"fields": {"issue": issue}})
        if not result.exit_code:
            logger.warning("Policy does not fail the pipeline on blocking issues")

    return result.exit_code


def main() -> None:
    configure_logging()
    _quieten_dependencies()
    args = parse_args()

    if not args.project_id or not args.mr_iid:
        logger.error(
            "Missing project ID or merge request IID. Pass --project-id/--mr-iid "
            "or set CI_PROJECT_ID/CI_MERGE_REQUEST_IID."
        )
        sys.exit(2)

    try:
        sys.exit(run(args))
    except MissingCredentialsError as exc:
        logger.error("Cannot reach the forge", extra={"fields": {"error": str(exc)}})
        sys.exit(2)
    except Exception as exc:
        logger.critical("Review run failed", extra={"fields": {"error": str(exc)}}, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
