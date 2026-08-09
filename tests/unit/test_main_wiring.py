"""What the operational flags actually do.

`--dry-run` and `--no-llm` are what make the agent adoptable: they let someone
run it against a real merge request without posting to it, and let a team run
the deterministic half without a model endpoint at all (finding G-13).

Both are only honest if they are wired, not merely parsed — hence behavioural
tests rather than argument-parsing ones. The parsing lives in
`tests/unit/test_cli.py`.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from code_reviewer.__main__ import EXIT_BLOCKED, EXIT_OK, _NoNarration, run
from code_reviewer.application.ports import ReviewBrief, Reviewer
from code_reviewer.cli import parse_args


def _args(*argv):
    return parse_args(["--project-id", "1", "--mr-iid", "2", *argv])


class _Result:
    def __init__(self, comment="the report", exit_code=EXIT_OK):
        self.comment = comment
        self.exit_code = exit_code
        self.metrics = []
        self.findings = []
        self.outcome = MagicMock(is_blocking=exit_code != EXIT_OK, blocking_issues=[])


class _Harness:
    """Stubs everything `run()` reaches for, recording what it was given."""

    def __enter__(self):
        self._patches = [
            patch("code_reviewer.__main__.load_policy"),
            patch("code_reviewer.__main__.GitLabForge"),
            patch("code_reviewer.__main__.ReviewService"),
            patch("code_reviewer.__main__.LLMFactory"),
            patch("code_reviewer.__main__.StaticAnalysisSuite"),
            patch("code_reviewer.__main__.set_workspace"),
            patch("code_reviewer.__main__._export_metrics"),
        ]
        (
            self.load_policy,
            self.forge,
            self.service,
            self.llm_factory,
            self.analysis,
            self.set_workspace,
            self.export_metrics,
        ) = [p.start() for p in self._patches]

        self.load_policy.return_value = MagicMock(version="1.0")
        self.service.return_value.review.return_value = _Result()
        return self

    def __exit__(self, *exc_info):
        for p in self._patches:
            p.stop()
        return False

    @property
    def service_kwargs(self):
        return self.service.call_args.kwargs

    @property
    def review_kwargs(self):
        return self.service.return_value.review.call_args.kwargs


class TestDryRun(unittest.TestCase):
    def test_the_workflow_is_told_not_to_publish(self):
        with _Harness() as harness:
            run(_args("--dry-run"))

        self.assertFalse(harness.review_kwargs["publish"])

    def test_a_normal_run_does_publish(self):
        with _Harness() as harness:
            run(_args())

        self.assertTrue(harness.review_kwargs["publish"])

    def test_the_report_is_printed(self):
        with _Harness(), patch("builtins.print") as printed:
            run(_args("--dry-run"))

        printed.assert_called_once()
        self.assertIn("the report", printed.call_args[0][0])

    def test_a_normal_run_prints_nothing(self):
        with _Harness(), patch("builtins.print") as printed:
            run(_args())

        printed.assert_not_called()

    def test_the_exit_code_is_still_the_real_one(self):
        """A dry run answers "what would this do", including "would it block"."""
        with _Harness() as harness:
            harness.service.return_value.review.return_value = _Result(exit_code=EXIT_BLOCKED)

            self.assertEqual(run(_args("--dry-run")), EXIT_BLOCKED)


class TestNoLlm(unittest.TestCase):
    def test_no_provider_is_constructed(self):
        """Not merely unused — `--no-llm` must need no endpoint at all."""
        with _Harness() as harness:
            run(_args("--no-llm"))

        harness.llm_factory.create_provider.assert_not_called()

    def test_a_normal_run_does_construct_one(self):
        with _Harness() as harness:
            run(_args())

        harness.llm_factory.create_provider.assert_called_once()

    def test_the_reviewer_is_the_null_narrator(self):
        with _Harness() as harness:
            run(_args("--no-llm"))

        self.assertIsInstance(harness.service_kwargs["reviewer"], _NoNarration)

    def test_the_analyzers_still_run(self):
        """The verdict comes from them, so this is not a degraded mode."""
        with _Harness() as harness:
            run(_args("--no-llm"))

        self.assertIsNotNone(harness.service_kwargs["analysis"])

    def test_the_null_narrator_satisfies_the_port(self):
        self.assertIsInstance(_NoNarration(), Reviewer)

    def test_its_output_explains_itself(self):
        """A blank section would leave a reader wondering what went wrong."""
        text = _NoNarration().review_diff(ReviewBrief(file_path="app.py", diff="+ line"))

        self.assertIn("--no-llm", text)
        self.assertIn("static analysis", text)


class TestOperationalPaths(unittest.TestCase):
    def test_the_repo_root_becomes_the_workspace(self):
        with _Harness() as harness, patch("code_reviewer.__main__.Workspace") as workspace:
            run(_args("--repo-root", "/srv/checkout"))

        workspace.from_environment.assert_called_once_with("/srv/checkout")
        harness.set_workspace.assert_called_once()

    def test_the_metrics_path_is_honoured(self):
        with _Harness() as harness:
            run(_args("--metrics-path", "build/metrics.txt"))

        self.assertEqual(harness.export_metrics.call_args[0][3], "build/metrics.txt")

    def test_the_default_metrics_path_is_unchanged(self):
        with _Harness() as harness:
            run(_args())

        self.assertEqual(harness.export_metrics.call_args[0][3], "metrics.txt")


class TestLogLevelReachesTheConfiguration(unittest.TestCase):
    def test_main_configures_logging_with_the_requested_level(self):
        from code_reviewer.__main__ import main

        with (
            patch("code_reviewer.__main__.configure_logging") as configure,
            patch("code_reviewer.__main__.parse_args") as parse,
            patch("code_reviewer.__main__.run") as runner,
        ):
            parse.return_value = MagicMock(project_id=1, mr_iid=2, log_level="DEBUG")
            runner.return_value = EXIT_OK

            with self.assertRaises(SystemExit):
                main()

        configure.assert_called_once_with("DEBUG")

    def test_configure_logging_really_accepts_a_level(self):
        """The mock above cannot catch a signature mismatch — this can.

        `configure_logging(stream=None)` used to be the only parameter, so
        `configure_logging("DEBUG")` would have passed the string as the output
        stream and produced a handler writing to a string.
        """
        import io
        import logging

        from code_reviewer.infrastructure.observability.logging import configure_logging

        logger = configure_logging("DEBUG", stream=io.StringIO())

        self.assertEqual(logger.level, logging.DEBUG)

    def test_an_explicit_level_beats_the_environment(self):
        """A flag that loses to a variable is not a flag."""
        import io
        import logging
        import os

        from code_reviewer.infrastructure.observability.logging import configure_logging

        with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}):
            logger = configure_logging("DEBUG", stream=io.StringIO())

        self.assertEqual(logger.level, logging.DEBUG)

    def test_an_unrecognised_level_falls_back_rather_than_raising(self):
        import io
        import logging

        from code_reviewer.infrastructure.observability.logging import configure_logging

        logger = configure_logging("VERBOSE", stream=io.StringIO())

        self.assertEqual(logger.level, logging.INFO)


if __name__ == "__main__":
    unittest.main()


class TestProjectMemoryWiring(unittest.TestCase):
    """Level 14 — the switches around the review history."""

    def test_memory_is_built_by_default_inside_the_workspace(self):
        from code_reviewer.__main__ import _build_memory
        from code_reviewer.infrastructure.memory.json_store import DEFAULT_MEMORY_FILENAME
        from code_reviewer.infrastructure.tools import Workspace

        workspace = Workspace(".")

        memory = _build_memory(_args(), workspace)

        self.assertIsNotNone(memory)
        self.assertTrue(str(memory._store.path).endswith(DEFAULT_MEMORY_FILENAME))

    def test_no_memory_builds_nothing(self):
        """AC-17: the Level 13 behaviour, exactly."""
        from code_reviewer.__main__ import _build_memory
        from code_reviewer.infrastructure.tools import Workspace

        self.assertIsNone(_build_memory(_args("--no-memory"), Workspace(".")))

    def test_memory_path_overrides_the_default(self):
        from code_reviewer.__main__ import _build_memory
        from code_reviewer.infrastructure.tools import Workspace

        memory = _build_memory(_args("--memory-path", "/tmp/elsewhere.json"), Workspace("."))

        self.assertEqual(str(memory._store.path), "/tmp/elsewhere.json")


class TestCommitteeWiring(unittest.TestCase):
    """Level 15 — one agent or four."""

    def test_the_default_is_a_committee_of_every_specialism(self):
        from code_reviewer.__main__ import _build_reviewer
        from code_reviewer.application.orchestration_service import ReviewOrchestrator
        from code_reviewer.domain.orchestration import Specialism

        with patch("code_reviewer.__main__.LLMFactory.create_provider") as factory:
            factory.return_value = MagicMock()
            reviewer = _build_reviewer(_args())

        self.assertIsInstance(reviewer, ReviewOrchestrator)
        self.assertEqual(set(reviewer._specialists), set(Specialism))

    def test_single_agent_builds_the_one_reviewer(self):
        """AC-17: the behaviour of every level before this one."""
        from code_reviewer.__main__ import _build_reviewer
        from code_reviewer.infrastructure.llm.review_agent import ReviewAgent

        with patch("code_reviewer.__main__.LLMFactory.create_provider") as factory:
            factory.return_value = MagicMock()
            reviewer = _build_reviewer(_args("--single-agent"))

        self.assertIsInstance(reviewer, ReviewAgent)

    def test_no_llm_still_wins_over_the_committee(self):
        from code_reviewer.__main__ import _build_reviewer, _NoNarration

        self.assertIsInstance(_build_reviewer(_args("--no-llm")), _NoNarration)

    def test_agent_totals_are_read_off_a_committee_and_absent_otherwise(self):
        from code_reviewer.__main__ import _agent_totals
        from code_reviewer.application.orchestration_service import AgentTotals
        from code_reviewer.domain.orchestration import Specialism

        committee = MagicMock()
        committee.agent_totals = {Specialism.SECURITY: AgentTotals(runs=2, failures=1, tool_calls=7)}

        self.assertEqual(_agent_totals(committee), {"security": (2, 1, 7)})
        self.assertEqual(_agent_totals(object()), {})


class TestTraceWiring(unittest.TestCase):
    """Level 16 — recording always, writing on request."""

    def test_the_trace_is_written_when_a_path_is_given(self):
        import json

        from code_reviewer.__main__ import _export_trace
        from code_reviewer.domain.trace import SpanKind
        from code_reviewer.infrastructure.observability.tracer import SpanRecorder

        tracer = SpanRecorder(trace_id="7-9")
        with tracer.span(SpanKind.REVIEW, "review"):
            pass

        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, "trace.json")
            _export_trace(tracer, destination)

            with open(destination, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["trace_id"], "7-9")

    def test_nothing_is_written_without_a_path(self):
        from code_reviewer.__main__ import _export_trace
        from code_reviewer.domain.trace import SpanKind
        from code_reviewer.infrastructure.observability.tracer import SpanRecorder

        tracer = SpanRecorder(trace_id="7-9")
        with tracer.span(SpanKind.REVIEW, "review"):
            pass

        with tempfile.TemporaryDirectory() as directory:
            _export_trace(tracer, "")

            self.assertEqual(os.listdir(directory), [])

    def test_an_empty_trace_writes_nothing_and_logs_nothing(self):
        from code_reviewer.__main__ import _export_trace
        from code_reviewer.infrastructure.observability.tracer import SpanRecorder

        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, "trace.json")
            _export_trace(SpanRecorder(), destination)

            self.assertEqual(os.listdir(directory), [])


class TestConcurrencyWiring(unittest.TestCase):
    """Level 17 — one worker is the old path, not a pool of one."""

    def test_one_worker_selects_the_sequential_runner(self):
        from code_reviewer.__main__ import _build_runner
        from code_reviewer.application.tasks import SequentialRunner

        self.assertIsInstance(_build_runner(_args("--concurrency", "1")), SequentialRunner)

    def test_more_than_one_worker_builds_a_pool_with_that_ceiling(self):
        from code_reviewer.__main__ import _build_runner
        from code_reviewer.infrastructure.concurrency.thread_pool import ThreadPoolRunner

        runner = _build_runner(_args("--concurrency", "6"))

        self.assertIsInstance(runner, ThreadPoolRunner)
        self.assertEqual(runner.max_workers, 6)

    def test_a_concurrency_below_one_is_refused_at_parse_time(self):
        with self.assertRaises(SystemExit):
            _args("--concurrency", "0")

    def test_a_non_numeric_concurrency_is_refused(self):
        with self.assertRaises(SystemExit):
            _args("--concurrency", "many")
