"""Step 1 — what a span is, and what it refuses to carry."""

import pytest

from code_reviewer.domain.trace import MAX_ATTRIBUTE_CHARS, Span, SpanKind, SpanStatus


def _span(**overrides) -> Span:
    defaults = {
        "span_id": "1.2",
        "parent_id": "1",
        "kind": SpanKind.AGENT,
        "name": "security",
        "started_ms": 1_000,
        "ended_ms": 1_250,
    }
    return Span(**{**defaults, **overrides})


def test_a_span_carries_what_it_was_and_how_long_it_took():
    span = _span()

    assert span.span_id == "1.2"
    assert span.parent_id == "1"
    assert span.kind is SpanKind.AGENT
    assert span.name == "security"
    assert span.duration_ms == 250
    assert span.status is SpanStatus.OK


def test_an_unfinished_span_has_no_duration_rather_than_zero():
    """Those are different facts, and a zero would be graphed."""
    assert _span(ended_ms=None).duration_ms is None
    assert not _span(ended_ms=None).is_finished


def test_a_span_that_ends_before_it_starts_is_refused():
    with pytest.raises(ValueError):
        _span(started_ms=2_000, ended_ms=1_000)


def test_a_span_of_no_duration_is_allowed():
    """Two calls to a millisecond clock inside one fast operation."""
    assert _span(started_ms=5, ended_ms=5).duration_ms == 0


def test_a_root_span_has_no_parent():
    assert _span(span_id="1", parent_id="").parent_id == ""


# -- attributes --------------------------------------------------------------


def test_attributes_are_immutable_and_copied():
    mutable = {"path": "src/app.py"}
    span = _span(attributes=mutable)

    mutable["path"] = "changed"

    assert span.attributes["path"] == "src/app.py"
    with pytest.raises(TypeError):
        span.attributes["path"] = "no"  # type: ignore[index]


def test_a_long_attribute_is_refused():
    """A long attribute is how a diff gets into a trace.

    The cap is a mechanism rather than advice: a trace is written to an
    artefact anyone with pipeline access can read, and a diff may contain a
    secret (Level 16, decision D-5).
    """
    with pytest.raises(ValueError):
        _span(attributes={"diff": "x" * (MAX_ATTRIBUTE_CHARS + 1)})


def test_an_attribute_at_the_cap_is_allowed():
    assert _span(attributes={"path": "x" * MAX_ATTRIBUTE_CHARS}).attributes["path"]


def test_a_numeric_attribute_is_not_measured_as_text():
    assert _span(attributes={"budget": 12_000}).attributes["budget"] == 12_000


def test_a_span_with_no_attributes_has_an_empty_mapping():
    assert dict(_span().attributes) == {}


# -- status ------------------------------------------------------------------


def test_a_failed_span_records_what_failed():
    span = _span(status=SpanStatus.ERROR, error_type="TimeoutError")

    assert span.status is SpanStatus.ERROR
    assert span.error_type == "TimeoutError"


def test_a_failed_span_without_an_error_type_is_refused():
    """The same rule a failed AgentReport follows: a failure that says only
    'it failed' is a failure nobody can act on."""
    with pytest.raises(ValueError):
        _span(status=SpanStatus.ERROR)


def test_a_successful_span_may_not_claim_an_error():
    with pytest.raises(ValueError):
        _span(status=SpanStatus.OK, error_type="TimeoutError")


def test_spans_are_values():
    assert _span() == _span()
    assert len({_span(), _span()}) == 1
