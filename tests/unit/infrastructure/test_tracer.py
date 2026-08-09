"""Step 4 — the recorder."""

import pytest

from code_reviewer.application.tracing import NullTracer
from code_reviewer.domain.trace import SpanKind, SpanStatus
from code_reviewer.infrastructure.observability.tracer import (
    SpanRecorder,
    current_trace_context,
    get_tracer,
    set_tracer,
)


class Clock:
    """A clock a test can move."""

    def __init__(self, *readings):
        self.readings = list(readings)
        self.now = 0

    def __call__(self) -> int:
        if self.readings:
            self.now = self.readings.pop(0)
        return self.now


@pytest.fixture(autouse=True)
def _restore_ambient_tracer():
    yield
    set_tracer(None)


def _by_id(tracer: SpanRecorder):
    return {span.span_id: span for span in tracer.trace().spans}


# -- nesting -----------------------------------------------------------------


def test_spans_nest_and_siblings_do_not():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.REVIEW, "run"):
        with tracer.span(SpanKind.FILE, "a.py"):
            with tracer.span(SpanKind.TOOL, "read_file"):
                pass
        with tracer.span(SpanKind.FILE, "b.py"):
            pass

    spans = _by_id(tracer)
    assert spans["1.1"].parent_id == "1"
    assert spans["1.1.1"].parent_id == "1.1"
    assert spans["1.2"].parent_id == "1"


def test_identifiers_are_dotted_counters():
    """`1.2.3` beats a hex string nobody can compare by eye, and it makes the
    tree's shape visible in a flat log."""
    tracer = SpanRecorder()

    with tracer.span(SpanKind.REVIEW, "run"):
        with tracer.span(SpanKind.FILE, "a"):
            pass
        with tracer.span(SpanKind.FILE, "b"):
            for name in ("x", "y", "z"):
                with tracer.span(SpanKind.TOOL, name):
                    pass

    assert set(_by_id(tracer)) == {"1", "1.1", "1.2", "1.2.1", "1.2.2", "1.2.3"}


def test_the_current_span_is_readable_inside_and_empty_outside():
    tracer = SpanRecorder()

    assert tracer.current_span_id == ""
    with tracer.span(SpanKind.REVIEW, "run"):
        assert tracer.current_span_id == "1"
        with tracer.span(SpanKind.FILE, "a"):
            assert tracer.current_span_id == "1.1"
        assert tracer.current_span_id == "1"
    assert tracer.current_span_id == ""


def test_two_top_level_spans_are_numbered_in_sequence():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.REVIEW, "one"):
        pass
    with tracer.span(SpanKind.REVIEW, "two"):
        pass

    assert set(_by_id(tracer)) == {"1", "2"}


# -- timing and failure ------------------------------------------------------


def test_a_span_records_how_long_it_took():
    tracer = SpanRecorder(clock=Clock(100, 350))

    with tracer.span(SpanKind.AGENT, "security"):
        pass

    assert _by_id(tracer)["1"].duration_ms == 250


def test_a_clock_that_goes_backwards_produces_zero_rather_than_a_negative():
    """A clock that moved backwards is not evidence of negative work, and a
    Span refuses to be built from one."""
    tracer = SpanRecorder(clock=Clock(500, 100))

    with tracer.span(SpanKind.AGENT, "security"):
        pass

    assert _by_id(tracer)["1"].duration_ms == 0


def test_an_exception_marks_the_span_and_propagates():
    """Tracing observes; it does not handle."""
    tracer = SpanRecorder()

    with pytest.raises(TimeoutError):
        with tracer.span(SpanKind.MODEL, "invoke"):
            raise TimeoutError("the endpoint went away")

    span = _by_id(tracer)["1"]
    assert span.status is SpanStatus.ERROR
    assert span.error_type == "TimeoutError"


def test_a_failure_inside_does_not_orphan_the_spans_around_it():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.FILE, "a.py"):
        with pytest.raises(ValueError):
            with tracer.span(SpanKind.AGENT, "security"):
                raise ValueError("no")
        with tracer.span(SpanKind.AGENT, "architecture"):
            pass

    assert set(_by_id(tracer)) == {"1", "1.1", "1.2"}
    assert tracer.trace().anomalies == ()


def test_finishing_a_span_twice_is_logged_and_ignored(caplog):
    tracer = SpanRecorder()
    span_id = tracer.start(SpanKind.TOOL, "grep")
    tracer.finish(span_id)

    with caplog.at_level("WARNING", logger="code_reviewer.infrastructure.observability.tracer"):
        tracer.finish(span_id)

    assert len(tracer.trace()) == 1
    assert "finished twice" in caplog.text


def test_finishing_something_that_was_never_started_is_ignored():
    tracer = SpanRecorder()

    tracer.finish("9.9")

    assert len(tracer.trace()) == 0


# -- attributes --------------------------------------------------------------


def test_attributes_travel_with_the_span():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.AGENT, "security", budget=4_000, path="src/app.py"):
        pass

    assert _by_id(tracer)["1"].attributes["budget"] == 4_000
    assert _by_id(tracer)["1"].attributes["path"] == "src/app.py"


def test_an_open_span_can_be_annotated_with_what_it_learned():
    tracer = SpanRecorder()

    with tracer.span(SpanKind.AGENT, "security") as span_id:
        tracer.annotate(span_id, tool_calls=3)

    assert _by_id(tracer)["1"].attributes["tool_calls"] == 3


def test_annotating_something_that_is_not_open_is_ignored():
    tracer = SpanRecorder()

    tracer.annotate("9.9", anything=1)

    assert len(tracer.trace()) == 0


# -- the null tracer ---------------------------------------------------------


def test_the_null_tracer_records_nothing_and_costs_nothing():
    tracer = NullTracer()

    with tracer.span(SpanKind.REVIEW, "run"):
        with tracer.span(SpanKind.TOOL, "grep"):
            pass

    assert len(tracer.trace()) == 0
    assert tracer.trace().tree() is None


def test_the_null_tracer_answers_the_same_questions():
    tracer = NullTracer()

    assert tracer.current_span_id == ""
    tracer.finish("anything")
    tracer.annotate("anything", x=1)


# -- the ambient tracer ------------------------------------------------------


def test_the_ambient_tracer_defaults_to_recording_nothing():
    assert isinstance(get_tracer(), NullTracer)
    assert current_trace_context() == ("", "")


def test_the_ambient_context_names_the_trace_and_the_open_span():
    tracer = SpanRecorder(trace_id="run-7")
    set_tracer(tracer)

    with tracer.span(SpanKind.REVIEW, "run"):
        with tracer.span(SpanKind.FILE, "a.py"):
            assert current_trace_context() == ("run-7", "1.1")


def test_outside_a_span_there_is_no_context_rather_than_an_empty_one():
    """A log record outside a review should carry no trace fields at all, not
    fields that say 'none'."""
    set_tracer(SpanRecorder(trace_id="run-7"))

    assert current_trace_context() == ("", "")


def test_clearing_the_ambient_tracer_restores_the_null_one():
    set_tracer(SpanRecorder(trace_id="run-7"))

    set_tracer(None)

    assert isinstance(get_tracer(), NullTracer)
