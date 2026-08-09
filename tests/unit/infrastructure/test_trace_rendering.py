"""Step 7 — reading a trace, as a person and as a machine."""

import json

from code_reviewer.domain.trace import Span, SpanKind, SpanStatus, Trace
from code_reviewer.infrastructure.observability.trace_rendering import (
    JsonTraceExporter,
    render_trace_tree,
    trace_to_json,
)


def _span(span_id, parent="", start=0, end=10, kind=SpanKind.TOOL, **overrides):
    return Span(
        span_id=span_id,
        parent_id=parent,
        kind=kind,
        name=overrides.pop("name", span_id),
        started_ms=start,
        ended_ms=end,
        **overrides,
    )


def _trace() -> Trace:
    return Trace(
        trace_id="run-7",
        spans=(
            _span("1", start=0, end=1000, kind=SpanKind.REVIEW, name="review"),
            _span("1.1", parent="1", start=0, end=900, kind=SpanKind.FILE, name="src/app.py"),
            _span(
                "1.1.1",
                parent="1.1",
                start=0,
                end=400,
                kind=SpanKind.AGENT,
                name="security",
                attributes={"budget": 4000},
            ),
            _span("1.1.2", parent="1.1", start=400, end=500, kind=SpanKind.MODEL, name="invoke"),
        ),
    )


# -- the tree ----------------------------------------------------------------


def test_the_tree_indents_by_depth():
    text = render_trace_tree(_trace())

    lines = {line.strip().split()[0]: line for line in text.splitlines() if line.strip()[:1] == "1"}
    assert lines["1"].startswith("1 ")
    assert lines["1.1"].startswith("  ")
    assert lines["1.1.1"].startswith("    ")


def test_each_line_names_the_kind_the_name_and_the_duration():
    text = render_trace_tree(_trace())

    assert "agent:security" in text
    assert "400 ms" in text


def test_a_parent_states_its_own_share_as_well_as_its_total():
    """A parent's duration includes everything below it, which is the number
    that hides where the time went."""
    text = render_trace_tree(_trace())

    assert "(self 400 ms)" in text  # 900 - 400 - 100


def test_a_leaf_does_not_repeat_its_duration_as_self_time():
    text = render_trace_tree(_trace())

    security = next(line for line in text.splitlines() if "agent:security" in line)
    assert "self" not in security


def test_attributes_are_shown():
    assert "budget=4000" in render_trace_tree(_trace())


def test_a_failed_span_is_marked_with_what_failed():
    trace = Trace(
        trace_id="t",
        spans=(
            _span("1", start=0, end=10, kind=SpanKind.REVIEW),
            _span(
                "1.1",
                parent="1",
                kind=SpanKind.AGENT,
                status=SpanStatus.ERROR,
                error_type="TimeoutError",
            ),
        ),
    )

    assert "✗ TimeoutError" in render_trace_tree(trace)


def test_the_summary_totals_self_time_by_kind():
    text = render_trace_tree(_trace())

    assert "Self time by kind:" in text
    assert "review 100 ms" in text


def test_anomalies_are_rendered():
    """An orphan span is a bug worth seeing."""
    trace = Trace(
        trace_id="t", spans=(_span("1", start=0, end=10), _span("9", parent="gone", start=1, end=2))
    )

    text = render_trace_tree(trace)

    assert "Anomalies:" in text
    assert "orphan" in text


def test_an_empty_trace_says_so():
    assert "No trace" in render_trace_tree(Trace(trace_id="t", spans=()))


# -- bounds ------------------------------------------------------------------


def test_the_tree_is_bounded_by_depth_and_says_what_it_omitted():
    spans = [_span("1", start=0, end=100, kind=SpanKind.REVIEW)]
    parent = "1"
    for _ in range(6):
        child = f"{parent}.1"
        spans.append(_span(child, parent=parent, start=0, end=10))
        parent = child

    text = render_trace_tree(Trace(trace_id="t", spans=tuple(spans)), max_depth=2)

    assert "not shown" in text
    assert "1.1.1.1.1" not in text


def test_the_tree_is_bounded_by_node_count_and_says_what_it_omitted():
    spans = [_span("1", start=0, end=100, kind=SpanKind.REVIEW)]
    spans += [_span(f"1.{index}", parent="1", start=index, end=index + 1) for index in range(30)]

    text = render_trace_tree(Trace(trace_id="t", spans=tuple(spans)), max_nodes=5)

    assert "not shown" in text
    assert len([line for line in text.splitlines() if line.strip().startswith("1.")]) <= 5


def test_the_rendering_is_deterministic():
    assert render_trace_tree(_trace()) == render_trace_tree(_trace())


# -- json --------------------------------------------------------------------


def test_the_json_names_every_span_and_round_trips():
    document = json.loads(json.dumps(trace_to_json(_trace())))

    assert document["trace_id"] == "run-7"
    assert {span["span_id"] for span in document["spans"]} == {"1", "1.1", "1.1.1", "1.1.2"}
    assert document["duration_ms"] == 1000


def test_the_json_carries_self_time_and_the_critical_path():
    document = trace_to_json(_trace())

    by_id = {span["span_id"]: span for span in document["spans"]}
    assert by_id["1.1"]["self_ms"] == 400
    assert document["critical_path"] == ["1", "1.1", "1.1.1"]


def test_the_json_carries_anomalies():
    trace = Trace(trace_id="t", spans=(_span("1"), _span("9", parent="gone", start=1, end=2)))

    assert trace_to_json(trace)["anomalies"]


# -- the exporter ------------------------------------------------------------


def test_the_exporter_writes_a_file_that_parses(tmp_path):
    destination = tmp_path / "traces" / "trace.json"

    JsonTraceExporter(destination).export(_trace())

    assert json.loads(destination.read_text(encoding="utf-8"))["trace_id"] == "run-7"


def test_an_exporter_that_cannot_write_is_logged_rather_than_fatal(tmp_path, caplog):
    """AC-17. An observability feature that can break the thing it observes is
    a liability."""
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")

    with caplog.at_level("WARNING", logger="code_reviewer.infrastructure.observability.trace_rendering"):
        JsonTraceExporter(blocked / "trace.json").export(_trace())

    assert "Could not write the trace" in caplog.text
