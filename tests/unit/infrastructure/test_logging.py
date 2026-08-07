"""Unit tests for logging configuration.

Diagnostics used to be 32 `print()` calls with hand-written `[INFO]` and
`[WARNING]` prefixes. There was no way to quieten a noisy run, no way to make a
silent failure louder, and nothing a log aggregator could parse (finding F-47).
"""

import json
import logging
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
                    if stripped.startswith("#"):
                        continue
                    offenders.append(f"{path.name}:{number}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
