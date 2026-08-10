"""Unit tests for logging configuration.

Diagnostics used to be 32 `print()` calls with hand-written `[INFO]` and
`[WARNING]` prefixes. There was no way to quieten a noisy run, no way to make a
silent failure louder, and nothing a log aggregator could parse (finding F-47).
"""

import json
import logging
import os
import unittest
from io import StringIO
from unittest.mock import patch

from code_reviewer.infrastructure.observability.logging import (
    JsonFormatter,
    StructuredFormatter,
    configure_logging,
    get_logger,
)


def _capture(logger_name="code_reviewer.test", **env):
    """Configures logging into a buffer and returns (logger, buffer)."""
    stream = StringIO()
    with patch.dict("os.environ", env, clear=True):
        configure_logging(stream=stream)
    return get_logger(logger_name), stream


class TestLevels(unittest.TestCase):
    def tearDown(self):
        configure_logging(stream=StringIO())

    def test_info_is_emitted_by_default(self):
        logger, stream = _capture()

        logger.info("hello")

        self.assertIn("hello", stream.getvalue())

    def test_debug_is_suppressed_by_default(self):
        logger, stream = _capture()

        logger.debug("noisy detail")

        self.assertNotIn("noisy detail", stream.getvalue())

    def test_log_level_raises_the_threshold(self):
        logger, stream = _capture(LOG_LEVEL="WARNING")

        logger.info("hello")
        logger.warning("careful")

        self.assertNotIn("hello", stream.getvalue())
        self.assertIn("careful", stream.getvalue())

    def test_log_level_lowers_the_threshold(self):
        logger, stream = _capture(LOG_LEVEL="DEBUG")

        logger.debug("noisy detail")

        self.assertIn("noisy detail", stream.getvalue())

    def test_an_unknown_level_falls_back_to_info(self):
        logger, stream = _capture(LOG_LEVEL="CHATTY")

        logger.info("hello")

        self.assertIn("hello", stream.getvalue())

    def test_level_is_case_insensitive(self):
        logger, stream = _capture(LOG_LEVEL="warning")

        logger.info("hello")

        self.assertNotIn("hello", stream.getvalue())


class TestStructuredFields(unittest.TestCase):
    def tearDown(self):
        configure_logging(stream=StringIO())

    def test_fields_are_appended_as_key_values(self):
        logger, stream = _capture()

        logger.info("triaged", extra={"fields": {"path": "src/app.py", "decision": "full"}})

        output = stream.getvalue()
        self.assertIn("path=src/app.py", output)
        self.assertIn("decision=full", output)

    def test_a_record_without_fields_still_renders(self):
        logger, stream = _capture()

        logger.info("plain message")

        self.assertIn("plain message", stream.getvalue())

    def test_values_with_spaces_are_quoted(self):
        logger, stream = _capture()

        logger.info("noted", extra={"fields": {"reason": "two words"}})

        self.assertIn('reason="two words"', stream.getvalue())


class TestJsonFormat(unittest.TestCase):
    def tearDown(self):
        configure_logging(stream=StringIO())

    def test_json_format_emits_one_object_per_line(self):
        logger, stream = _capture(LOG_FORMAT="json")

        logger.info("triaged", extra={"fields": {"path": "src/app.py"}})

        line = stream.getvalue().strip()
        record = json.loads(line)
        self.assertEqual(record["message"], "triaged")
        self.assertEqual(record["path"], "src/app.py")

    def test_json_records_carry_level_and_logger(self):
        logger, stream = _capture(LOG_FORMAT="json")

        logger.warning("careful")

        record = json.loads(stream.getvalue().strip())
        self.assertEqual(record["level"], "WARNING")
        self.assertEqual(record["logger"], "code_reviewer.test")

    def test_json_records_include_an_exception_when_present(self):
        logger, stream = _capture(LOG_FORMAT="json")

        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("failed")

        record = json.loads(stream.getvalue().strip())
        self.assertIn("ValueError: boom", record["exception"])


class TestIdempotence(unittest.TestCase):
    def tearDown(self):
        configure_logging(stream=StringIO())

    def test_configuring_twice_does_not_duplicate_output(self):
        stream = StringIO()
        with patch.dict("os.environ", {}, clear=True):
            configure_logging(stream=stream)
            configure_logging(stream=stream)

        get_logger("code_reviewer.test").info("once")

        self.assertEqual(stream.getvalue().count("once"), 1)


class TestFormattersDirectly(unittest.TestCase):
    def _record(self, **fields):
        record = logging.LogRecord(
            name="code_reviewer.x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="message",
            args=(),
            exc_info=None,
        )
        if fields:
            record.fields = fields
        return record

    def test_structured_formatter_without_fields(self):
        self.assertIn("message", StructuredFormatter().format(self._record()))

    def test_json_formatter_without_fields(self):
        record = json.loads(JsonFormatter().format(self._record()))

        self.assertEqual(record["message"], "message")

    def test_json_formatter_renders_non_string_values(self):
        record = json.loads(JsonFormatter().format(self._record(count=3, ratio=0.5)))

        self.assertEqual(record["count"], 3)
        self.assertEqual(record["ratio"], 0.5)


#: Marks a `print` that is the program's output rather than a diagnostic.
STDOUT_MARKER = "# stdout:"


class TestNoPrints(unittest.TestCase):
    def test_the_package_does_not_print(self):
        """Regression for F-47.

        A print cannot be levelled, filtered or shipped. Anything worth saying
        goes through a logger.
        """
        from pathlib import Path

        package = Path(__file__).resolve().parents[3] / "code_reviewer"
        offenders = []
        for path in package.rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("print(") or " print(" in stripped:
                    if stripped.startswith("#") or STDOUT_MARKER in line:
                        continue
                    offenders.append(f"{path.name}:{number}")

        self.assertEqual(offenders, [])

    def test_the_exemption_is_used_sparingly(self):
        """One marked line, in the composition root, and no more.

        The rule is about *diagnostics*: a print cannot be levelled, filtered
        or shipped. It is not about a program's own output — `--dry-run` puts
        the report on stdout so it can be piped, and a logger would prefix it
        with a timestamp and a level and make it useless for that.

        Distinguishing the two is worth an explicit marker rather than a
        blanket exception, because the second an unmarked print is allowed the
        first kind comes back.
        """
        from pathlib import Path

        package = Path(__file__).resolve().parents[3] / "code_reviewer"
        # Asserted on the file and the count, not the line number: a test
        # that breaks when something above it moves is a test that gets
        # deleted rather than understood.
        marked = sorted(
            str(path.relative_to(package))
            for path in package.rglob("*.py")
            for line in path.read_text(encoding="utf-8").splitlines()
            if STDOUT_MARKER in line and "print(" in line
        )

        # Four entry points, and only entry points: `__main__` prints the
        # review under `--dry-run`, `audit` prints two outcomes and the four
        # reasons it could not reach one, `evaluate` prints its five reports —
        # analyzers, narration, documentation, retrieval and prompt alignment —
        # a baseline comparison, the reasons a measurement could not be
        # produced and the ways a live run is incomplete, and `serve` prints
        # the one reason it refuses to start. Everything below them logs.
        self.assertEqual(
            marked,
            ["__main__.py"] + ["audit.py"] * 6 + ["evaluate.py"] * 17 + ["serve.py"],
            marked,
        )


if __name__ == "__main__":
    unittest.main()


class TestTraceContextOnEveryRecord(unittest.TestCase):
    """Level 16 — the join between a log line and a trace."""

    def setUp(self):
        from code_reviewer.infrastructure.observability.tracer import SpanRecorder, set_tracer

        self.tracer = SpanRecorder(trace_id="run-7")
        set_tracer(self.tracer)
        self.addCleanup(set_tracer, None)

    def _emit(self, use_json: bool = False) -> str:
        from code_reviewer.domain.trace import SpanKind

        stream = StringIO()
        with patch.dict(os.environ, {"LOG_FORMAT": "json" if use_json else ""}, clear=False):
            logger = configure_logging("INFO", stream=stream)
            with self.tracer.span(SpanKind.REVIEW, "run"):
                with self.tracer.span(SpanKind.FILE, "a.py"):
                    logger.info("inside")
            logger.info("outside")
        return stream.getvalue()

    def test_the_structured_format_carries_the_trace_and_the_span(self):
        output = self._emit()

        inside = next(line for line in output.splitlines() if "inside" in line)
        self.assertIn("trace_id=run-7", inside)
        self.assertIn("span_id=1.1", inside)

    def test_the_json_format_carries_the_trace_and_the_span(self):
        output = self._emit(use_json=True)

        inside = json.loads(next(line for line in output.splitlines() if "inside" in line))
        self.assertEqual(inside["trace_id"], "run-7")
        self.assertEqual(inside["span_id"], "1.1")

    def test_a_record_outside_a_span_carries_neither(self):
        """Not fields that say 'none'."""
        output = self._emit(use_json=True)

        outside = json.loads(next(line for line in output.splitlines() if "outside" in line))
        self.assertNotIn("trace_id", outside)
        self.assertNotIn("span_id", outside)

    def test_a_callers_own_trace_id_is_not_overwritten(self):
        from code_reviewer.domain.trace import SpanKind

        stream = StringIO()
        logger = configure_logging("INFO", stream=stream)
        with self.tracer.span(SpanKind.REVIEW, "run"):
            logger.info("mine", extra={"fields": {"trace_id": "chosen"}})

        self.assertIn("trace_id=chosen", stream.getvalue())
