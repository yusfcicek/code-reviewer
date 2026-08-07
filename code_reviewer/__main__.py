"""Entry point for the Enterprise AI Code Review Agent.

Orchestrates one review run:

1. Load configuration and policy.
2. Connect to GitLab and fetch the merge request's changes.
3. Triage each file (SKIP, AUTO_APPROVE, QUICK_SCAN, FULL_REVIEW, CRITICAL).
4. Run the review agent on the files that warrant it.
5. Evaluate the review gate and aggregate the verdict.
6. Export metrics and post the report.
7. Exit with the code the policy implies.

Usage:
    ai-code-review --project-id <ID> --mr-iid <IID> [--policy <path>]
"""

import logging
import sys
import time
import warnings

from code_reviewer.cli import parse_args
from code_reviewer.infrastructure.config.loader import load_policy
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.gate import ReviewGate
from code_reviewer.infrastructure.memory.smart_memory import SmartMemoryStrategy
from code_reviewer.infrastructure.metrics.collector import MetricsCollector, ReviewMetrics
from code_reviewer.infrastructure.forge.client import (
    MissingCredentialsError,
    build_gitlab_client,
)
from code_reviewer.infrastructure.llm.vllm import LLMFactory
from code_reviewer.application.report import render_review_comment
from code_reviewer.domain.triage import ReviewDecision, ReviewTriage

#: Triage decisions that require the model rather than a rule.
_NEEDS_AGENT = {
    ReviewDecision.QUICK_SCAN,
    ReviewDecision.FULL_REVIEW,
    ReviewDecision.CRITICAL,
}


def _quieten_dependencies() -> None:
    """Keeps third-party chatter out of the CI log."""
    for name in ("tiktoken", "langchain", "openai", "httpx"):
        logging.getLogger(name).setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=".*model not found.*")


def _fetch_file_content(project, file_path: str, ref: str):
    """Returns the file's content at ``ref``, or ``None`` if it cannot be read.

    A file may legitimately be unreadable — it can be binary, or the ref may
    have moved — and that is not a reason to abandon the review.
    """
    try:
        blob = project.files.get(file_path=file_path, ref=ref)
        return blob.decode().decode("utf-8")
    except Exception as exc:
        print(f"[INFO] Full content unavailable for {file_path}: {exc}")
        return None


def run_review(args) -> int:
    """Runs one review and returns the process exit code."""
    print(f"[INFO] Initializing agent for project {args.project_id}, MR !{args.mr_iid}...")

    policy = load_policy(args.policy)
    print(f"[INFO] Review policy loaded (v{policy.version})")

    provider = LLMFactory.create_provider("vllm")
    memory = SmartMemoryStrategy(provider)
    agent = ReviewAgent(provider, memory)
    triage = ReviewTriage(policy)
    gate = ReviewGate(policy)
    metrics_collector = MetricsCollector()
    outcome = ReviewOutcome()

    gl = build_gitlab_client()
    project = gl.projects.get(args.project_id)
    merge_request = project.mergerequests.get(args.mr_iid)
    print(f"[INFO] Connected to GitLab. Project: {project.name}, MR: !{args.mr_iid}")

    changes = merge_request.changes()["changes"]
    print(f"[INFO] Found {len(changes)} changes.")
    if not changes:
        print("[WARNING] No changes found.")
        return 0

    # Cross-file context: what else moved in this merge request.
    all_changed_files = [c["new_path"] for c in changes if not c["deleted_file"]]

    sections = []
    for change in changes:
        new_path = change["new_path"]
        if change["deleted_file"]:
            print(f"[INFO] Skipping deleted file: {new_path}")
            continue

        diff = change["diff"]
        started_at = time.time()

        full_content = _fetch_file_content(project, new_path, merge_request.sha)

        triage_result = triage.decide(diff, new_path, full_content)
        print(f"[TRIAGE] {new_path}: {triage_result.decision.value} ({triage_result.reason})")

        if triage_result.decision is ReviewDecision.SKIP:
            continue

        gate_evaluation = None
        if triage_result.decision is ReviewDecision.AUTO_APPROVE:
            sections.append(
                f"## ✅ Auto-Approved: `{new_path}`\n> {triage_result.reason}\n\n---\n"
            )
            outcome.record_unevaluated(new_path)
        elif triage_result.decision in _NEEDS_AGENT:
            print(f"[AGENT] analyzing {new_path}...")
            review_text = agent.review_diff(
                new_path, diff, full_content, other_files=all_changed_files
            )
            sections.append(f"## Review for `{new_path}`\n\n{review_text}\n\n---\n")

            gate_evaluation = gate.evaluate(review_text)
            outcome.record(new_path, gate_evaluation)

        metrics_collector.record(
            ReviewMetrics(
                project_id=str(args.project_id),
                mr_id=str(args.mr_iid),
                files_analyzed=1,
                lines_analyzed=len(diff.splitlines()),
                triage_decisions={triage_result.decision.value: 1},
                gate_result=gate_evaluation.result.value if gate_evaluation else "pass",
                quality_score=(gate_evaluation.scores.get("quality") or 0)
                if gate_evaluation
                else 0,
                duration_ms=int((time.time() - started_at) * 1000),
            )
        )

    if sections:
        comment = render_review_comment(policy.version, outcome, sections)
        merge_request.notes.create({"body": comment})
        print("[INFO] Review posted to GitLab.")

    metrics_collector.export_gitlab_metrics("metrics.txt")
    print("[INFO] Metrics exported.")

    exit_code = outcome.exit_code(policy)
    if exit_code:
        print("[GATE] Pipeline failed due to blocking issues:")
        for issue in outcome.blocking_issues:
            print(f"  - {issue}")
    elif outcome.is_blocking:
        print("[GATE] Blocking issues found, but the policy does not fail the pipeline.")

    return exit_code


def main() -> None:
    _quieten_dependencies()
    args = parse_args()

    if not args.project_id or not args.mr_iid:
        print("Missing project ID or MR IID. Pass --project-id/--mr-iid or set "
              "CI_PROJECT_ID/CI_MERGE_REQUEST_IID.")
        sys.exit(2)

    try:
        sys.exit(run_review(args))
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
