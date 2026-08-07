"""Composition root.

Builds the adapters, hands them to :class:`ReviewService` and exits with the
code the review implies. All the decisions live in the layers below; this
module only wires them together, which is why it is the one place allowed to
import from every layer.

Usage:
    ai-code-review --project-id <ID> --mr-iid <IID> [--policy <path>]
"""

import logging
import sys
import warnings

from code_reviewer.application.review_service import ReviewService
from code_reviewer.cli import parse_args
from code_reviewer.domain.triage import ReviewTriage
from code_reviewer.infrastructure.config.loader import load_policy
from code_reviewer.infrastructure.forge.client import MissingCredentialsError
from code_reviewer.infrastructure.forge.gitlab_forge import GitLabForge
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from code_reviewer.infrastructure.llm.vllm import LLMFactory
from code_reviewer.infrastructure.memory.smart_memory import SmartMemoryStrategy
from code_reviewer.infrastructure.metrics.collector import MetricsCollector, ReviewMetrics

#: Where GitLab CI picks up the metrics report artifact.
METRICS_PATH = "metrics.txt"


def _quieten_dependencies() -> None:
    """Keeps third-party chatter out of the CI log."""
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
                files_analyzed=1,
                lines_analyzed=metric.lines_analyzed,
                triage_decisions=metric.triage_decisions,
                gate_result=metric.gate_result,
                quality_score=metric.quality_score or 0,
                duration_ms=metric.duration_ms,
            )
        )
    collector.export_gitlab_metrics(METRICS_PATH)


def run(args) -> int:
    """Builds the workflow for one run and returns its exit code."""
    print(f"[INFO] Initializing agent for project {args.project_id}, MR !{args.mr_iid}...")

    policy = load_policy(args.policy)
    print(f"[INFO] Review policy loaded (v{policy.version})")

    provider = LLMFactory.create_provider("vllm")
    memory = SmartMemoryStrategy(provider)

    service = ReviewService(
        forge=GitLabForge(),
        reviewer=ReviewAgent(provider, memory),
        triage=ReviewTriage(policy),
        policy=policy,
    )

    result = service.review(args.project_id, args.mr_iid)

    if result.comment:
        print("[INFO] Review posted to GitLab.")
    else:
        print("[INFO] Nothing to review; no comment posted.")

    _export_metrics(result, args.project_id, args.mr_iid)
    print(f"[INFO] Metrics exported to {METRICS_PATH}.")

    if result.outcome.is_blocking:
        print("[GATE] Blocking issues:")
        for issue in result.outcome.blocking_issues:
            print(f"  - {issue}")
        if not result.exit_code:
            print("[GATE] Policy does not fail the pipeline on blocking issues.")

    return result.exit_code


def main() -> None:
    _quieten_dependencies()
    args = parse_args()

    if not args.project_id or not args.mr_iid:
        print(
            "Missing project ID or MR IID. Pass --project-id/--mr-iid or set "
            "CI_PROJECT_ID/CI_MERGE_REQUEST_IID."
        )
        sys.exit(2)

    try:
        sys.exit(run(args))
    except MissingCredentialsError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(2)
    except Exception as exc:
        print(f"[ERROR] Critical failure: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
