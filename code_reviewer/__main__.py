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

from code_reviewer.application.documentation_service import DocumentationService
from code_reviewer.application.drift_service import DriftService
from code_reviewer.application.governance import DecisionRecorder
from code_reviewer.application.orchestration_service import ReviewOrchestrator
from code_reviewer.application.ports import Reviewer
from code_reviewer.application.project_memory import ProjectMemory
from code_reviewer.application.review_service import ReviewService
from code_reviewer.application.tasks import SequentialRunner, TaskRunner
from code_reviewer.cli import parse_args
from code_reviewer.domain.orchestration import Specialism
from code_reviewer.domain.triage import ReviewTriage
from code_reviewer.errors import ConfigurationError, ReviewError
from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite
from code_reviewer.infrastructure.concurrency.thread_pool import ThreadPoolRunner
from code_reviewer.infrastructure.config.loader import load_policy
from code_reviewer.infrastructure.documentation.workspace import build_symbol_index, collect_documents
from code_reviewer.infrastructure.forge.gitlab_forge import GitLabForge
from code_reviewer.infrastructure.governance.identity import build_run_identity
from code_reviewer.infrastructure.governance.sealed_sink import SealedAuditSink
from code_reviewer.infrastructure.governance.signing import signer_from_environment
from code_reviewer.infrastructure.llm.drift_judge import ModelDriftJudge
from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
from code_reviewer.infrastructure.llm.specialist_agent import SpecialistAgent
from code_reviewer.infrastructure.llm.vllm import LLMFactory
from code_reviewer.infrastructure.memory.json_store import DEFAULT_MEMORY_FILENAME, JsonMemoryStore
from code_reviewer.infrastructure.memory.smart_memory import SmartMemoryStrategy
from code_reviewer.infrastructure.metrics.collector import MetricsCollector, ReviewMetrics
from code_reviewer.infrastructure.observability.logging import configure_logging, get_logger
from code_reviewer.infrastructure.observability.trace_rendering import JsonTraceExporter, render_trace_tree
from code_reviewer.infrastructure.observability.tracer import SpanRecorder, get_tracer, set_tracer
from code_reviewer.infrastructure.retrieval.corpus import build_retriever
from code_reviewer.infrastructure.retrieval.document_corpus import build_document_retriever
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

    def review_diff(self, brief) -> str:
        return (
            "_Narration was not requested (`--no-llm`). The verdict below comes "
            "from static analysis, which is where it always comes from._"
        )


def _export_metrics(result, project_id, merge_request_iid, metrics_path: str, reviewer=None) -> None:
    """Translates the workflow's facts into the exporter's format.

    ``reviewer`` is read for per-agent totals when it has them. Asked of the
    object rather than threaded through `ReviewService`, because how many
    agents produced a review is the reviewer's business and the workflow is
    deliberately unaware of it (Level 15, decision D-1).
    """
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
                recurring_findings=metric.recurring_findings,
            )
        )
    collector.export_gitlab_metrics(metrics_path, agents=_agent_totals(reviewer))


def _export_trace(tracer, trace_path: str) -> None:
    """Summarises the run's trace in the log, and writes it if asked.

    Recording is always on, because a trace nobody asked for is the one they
    want after a failure; writing a file is what the flag controls
    (decision D-4).
    """
    trace = tracer.trace()
    if not len(trace):
        return

    logger.info("Trace\n%s", render_trace_tree(trace))
    if trace_path:
        JsonTraceExporter(trace_path).export(trace)


def _agent_totals(reviewer) -> dict[str, tuple[int, int, int]]:
    """Runs, failures and tool calls per specialist, or nothing."""
    totals = getattr(reviewer, "agent_totals", None)
    if not totals:
        return {}
    return {
        specialism.value: (total.runs, total.failures, total.tool_calls)
        for specialism, total in totals.items()
    }


def build_review_service(args, tracer=None) -> tuple[ReviewService, Reviewer]:
    """Assembles the workflow from the arguments, and returns it with its reviewer.

    Extracted so the HTTP service builds exactly what the command line builds
    (Level 18). The reviewer comes back alongside because the metrics export
    asks it for its per-agent totals, and only the composition root knows
    whether there is a committee to ask.
    """
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

    # What previous reviews of this repository recorded. Informational only:
    # nothing it says reaches the gate (Level 14, decision D-4).
    memory = _build_memory(args, workspace)

    # One recorder for the run: handed to the workflow and the agents, and
    # set as the ambient one so the tool layer and the log filter can reach it
    # (Level 16, decision D-3). Under the service the worker sets its own, one
    # per job, so an injected tracer wins.
    if tracer is None:
        tracer = SpanRecorder(trace_id=f"{getattr(args, 'project_id', '')}-{getattr(args, 'mr_iid', '')}")
        set_tracer(tracer)

    # One provider per run, shared by the narrator and by Level 23's judge.
    # Two would be two connections, two token budgets and — the reason a test
    # pins it — two answers to "which model produced this review".
    provider = None if args.no_llm else LLMFactory.create_provider("vllm")
    reviewer = _build_reviewer(args, tracer, provider)

    # What this run decided, and under which versions. Written only where an
    # operator asked for it: a file appearing beside a checkout because a tool
    # was run is a surprise, and this one names merge requests (Level 20, D-7).
    recorder = _build_recorder(args, policy)

    # Level 23. Both tiers are optional and neither can block: they emit at or
    # below Severity.LOW, and the attribution table registers the retrieved one
    # as an agent. A checkout that yields no symbol index turns the first off
    # and says so in the report; a run with no reviewer turns the second off.
    documentation, drift = _build_documentation(args, provider)

    service = ReviewService(
        forge=GitLabForge(),
        reviewer=reviewer,
        triage=ReviewTriage(policy),
        policy=policy,
        analysis=StaticAnalysisSuite(policy),
        # The workspace records what it refused. A refused read is evidence
        # about the diff — the agent asked for that path because the content
        # under review led it to — so it reaches the gate as a finding.
        access_auditor=workspace,
        retriever=retriever,
        memory=memory,
        tracer=tracer,
        recorder=recorder,
        # Proposals, never applications: the flag turns off the offering, and
        # there has never been anything that applies one (Level 22).
        suggest_fixes=not getattr(args, "no_suggestions", False),
        documentation=documentation,
        drift=drift,
    )
    return service, reviewer


def _build_documentation(args, provider=None):
    """The two documentation tiers, or nothing when they cannot be built.

    Best-effort throughout, for the reason Level 13 gave about retrieval: this
    is an improvement to a report, never a precondition for producing one. A
    tree that will not index, a directory that is not there, an LLM provider
    that cannot be reached — each costs its own tier and leaves the review
    otherwise identical.
    """
    if getattr(args, "no_documentation", False):
        return None, None

    try:
        index = build_symbol_index(args.repo_root)
        documents = collect_documents(args.repo_root)
    except Exception as error:  # pragma: no cover - defensive, the builders log their own
        logger.warning("Documentation check unavailable: %s", error)
        return None, None

    documentation = DocumentationService(index=index, documents=documents)

    if provider is None or not documents:
        # No model or no prose: the retrieved tier has nothing to ask, or
        # nothing to ask about. The deterministic one still runs.
        return documentation, None

    # Its own index, holding only prose. Sharing the code index was the shape of
    # self-review finding S-01: code won every ranking, the limit was spent
    # before the document filter ran, and the tier returned nothing at all. The
    # retrieval *implementation* is still the single one Level 13 built.
    drift = DriftService(retriever=build_document_retriever(args.repo_root), judge=ModelDriftJudge(provider))
    return documentation, drift


def run(args) -> int:
    """Builds the workflow for one run and returns its exit code."""
    logger.info(
        "Starting review",
        extra={"fields": {"project": args.project_id, "merge_request": args.mr_iid}},
    )

    service, reviewer = build_review_service(args)
    tracer = get_tracer()

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

    _export_metrics(result, args.project_id, args.mr_iid, args.metrics_path, reviewer)
    _export_trace(tracer, args.trace_path)
    logger.info("Metrics exported", extra={"fields": {"path": args.metrics_path}})

    if result.outcome.is_blocking:
        for issue in result.outcome.blocking_issues:
            logger.error("Blocking issue", extra={"fields": {"issue": issue}})
        if not result.exit_code:
            logger.warning("Policy does not fail the pipeline on blocking issues")

    return result.exit_code


def _build_reviewer(args, tracer=None, provider=None) -> Reviewer:
    """The narrator, or a stand-in that produces none.

    The provider is passed in so one run builds one, shared with Level 23's
    judge. It is still constructed lazily when a caller does not supply one,
    so `--no-llm` needs no model endpoint at all — not merely an unused one.
    """
    if args.no_llm:
        logger.info("Running without a model; the verdict comes from static analysis either way")
        return _NoNarration()

    provider = provider or LLMFactory.create_provider("vllm")
    if args.single_agent:
        logger.info("Reviewing with one agent (--single-agent)")
        return ReviewAgent(provider, SmartMemoryStrategy(provider), tracer=tracer)

    # One memory strategy shared by the committee: a specialist that could not
    # see what the others noticed would repeat their work, and the strategy is
    # already what carries insight between files.
    memory_strategy = SmartMemoryStrategy(provider)
    orchestrator = ReviewOrchestrator(
        {specialism: SpecialistAgent(specialism, provider, memory_strategy) for specialism in Specialism}
    )
    logger.info(
        "Reviewing with a committee",
        extra={"fields": {"agents": [specialism.value for specialism in Specialism]}},
    )
    return orchestrator


def _build_runner(args) -> TaskRunner:
    """How the committee's members are run.

    One worker selects the sequential runner outright rather than a pool of
    one, so the old path stays the old path — including its inability to
    interrupt a hung task, which a pool of one would quietly acquire.
    """
    if args.concurrency <= 1:
        logger.info("Specialists run in sequence (--concurrency 1)")
        return SequentialRunner()

    logger.info("Specialists run concurrently", extra={"fields": {"workers": args.concurrency}})
    return ThreadPoolRunner(max_workers=args.concurrency)


def _build_recorder(args, policy) -> DecisionRecorder | None:
    """The decision recorder, or ``None`` when nobody asked for one.

    The identity is assembled here rather than inside the recorder because
    only the composition root knows which policy, which model and which
    prompts are actually in use.
    """
    path = getattr(args, "audit_path", "")
    if not path:
        return None

    signer = signer_from_environment()
    logger.info(
        "Recording the decision",
        extra={"fields": {"path": path, "signed": signer.is_signing, "key_id": signer.key_id}},
    )
    # Sealed rather than plain since Level 24: each line names the digest of
    # the one before it, so a deleted or reordered record is detectable without
    # trusting the file's length. Unsigned when no key was supplied — the links
    # are the cheaper guarantee and they cost no key at all.
    return DecisionRecorder(SealedAuditSink(path, signer=signer), build_run_identity(policy))


def _build_memory(args, workspace) -> ProjectMemory | None:
    """The project's review history, or ``None`` when it was turned off.

    The default location is inside the workspace, so the history travels with
    the checkout and a team can see, commit or delete it. `--no-memory`
    produces exactly the behaviour of every level before this one.
    """
    if args.no_memory:
        logger.info("Project memory disabled by --no-memory")
        return None

    path = args.memory_path or str(workspace.root / DEFAULT_MEMORY_FILENAME)
    logger.info("Project memory in use", extra={"fields": {"path": path}})
    return ProjectMemory(JsonMemoryStore(path))


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
