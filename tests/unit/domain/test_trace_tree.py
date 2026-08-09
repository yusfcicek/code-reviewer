"""Steps 2 and 3 — the tree, and where the time went."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.trace import Span, SpanKind, Trace


def _span(span_id: str, parent: str = "", start: int = 0, end: int | None = 10, kind=SpanKind.TOOL):
    return Span(
        span_id=span_id,
        parent_id=parent,
        kind=kind,
        name=span_id,
        started_ms=start,
        ended_ms=end,
    )


def _ids(node) -> list[str]:
    return [node.span.span_id, *[child for grandchild in node.children for child in _ids(grandchild)]]


# -- building ----------------------------------------------------------------


def test_a_flat_list_builds_one_tree():
    trace = Trace(
        trace_id="t",
        spans=(
            _span("1", start=0, end=100, kind=SpanKind.REVIEW),
            _span("1.1", parent="1", start=1, end=50),
            _span("1.2", parent="1", start=51, end=90),
            _span("1.1.1", parent="1.1", start=2, end=40),
        ),
    )

    root = trace.tree()

    assert root.span.span_id == "1"
    assert _ids(root) == ["1", "1.1", "1.1.1", "1.2"]
    assert trace.anomalies == ()


def test_children_are_ordered_by_start_then_by_id():
    trace = Trace(
        trace_id="t",
        spans=(
            _span("1", start=0, end=100),
            _span("1.b", parent="1", start=10, end=20),
            _span("1.a", parent="1", start=10, end=20),
            _span("1.c", parent="1", start=5, end=6),
        ),
    )

    assert [child.span.span_id for child in trace.tree().children] == ["1.c", "1.a", "1.b"]


def test_an_empty_trace_builds_nothing_rather_than_raising():
    assert Trace(trace_id="t", spans=()).tree() is None
    assert Trace(trace_id="t", spans=()).anomalies == ()


def test_a_single_span_is_its_own_root():
    trace = Trace(trace_id="t", spans=(_span("1"),))

    assert trace.tree().span.span_id == "1"
    assert trace.tree().children == ()


# -- bad input ---------------------------------------------------------------


def test_an_orphan_attaches_to_the_root_and_is_recorded():
    """Losing a span because its parent is missing loses exactly the
    information somebody is looking for."""
    trace = Trace(
        trace_id="t",
        spans=(_span("1", start=0, end=100), _span("9.9", parent="nowhere", start=5, end=6)),
    )

    assert "9.9" in _ids(trace.tree())
    assert any("9.9" in note and "orphan" in note for note in trace.anomalies)


def test_a_two_span_cycle_is_broken_and_recorded():
    trace = Trace(
        trace_id="t",
        spans=(_span("a", parent="b", start=0, end=10), _span("b", parent="a", start=1, end=9)),
    )

    root = trace.tree()

    assert root is not None
    assert sorted(_ids(root)) == ["a", "b"]
    assert any("cycle" in note for note in trace.anomalies)


def test_a_three_span_cycle_is_broken_and_recorded():
    trace = Trace(
        trace_id="t",
        spans=(
            _span("a", parent="c", start=0, end=10),
            _span("b", parent="a", start=1, end=9),
            _span("c", parent="b", start=2, end=8),
        ),
    )

    assert sorted(_ids(trace.tree())) == ["a", "b", "c"]
    assert any("cycle" in note for note in trace.anomalies)


def test_a_span_that_is_its_own_parent_is_broken_and_recorded():
    trace = Trace(trace_id="t", spans=(_span("a", parent="a"),))

    assert _ids(trace.tree()) == ["a"]
    assert any("cycle" in note for note in trace.anomalies)


def test_two_roots_keep_both_and_record_the_second():
    """Two roots is a bug in the recorder, not a reason to lose half the
    spans."""
    trace = Trace(trace_id="t", spans=(_span("1", start=0, end=100), _span("2", start=200, end=300)))

    root = trace.tree()

    assert root.span.span_id == "1"
    assert "2" in _ids(root)
    assert any("root" in note for note in trace.anomalies)


@given(
    st.lists(
        st.tuples(st.integers(0, 6), st.integers(-1, 6), st.integers(0, 50)),
        min_size=1,
        max_size=7,
        unique_by=lambda item: item[0],
    )
)
def test_building_terminates_and_keeps_every_span_exactly_once(rows):
    """AC-3 as a property. A tracer that hangs on its own output is worse
    than no tracer."""
    spans = tuple(
        _span(str(identifier), parent="" if parent < 0 else str(parent), start=start, end=start + 1)
        for identifier, parent, start in rows
    )
    trace = Trace(trace_id="t", spans=spans)

    root = trace.tree()

    assert root is not None
    assert sorted(_ids(root)) == sorted(span.span_id for span in spans)


# -- timing ------------------------------------------------------------------


def test_self_time_is_duration_minus_children():
    trace = Trace(
        trace_id="t",
        spans=(
            _span("1", start=0, end=100, kind=SpanKind.REVIEW),
            _span("1.1", parent="1", start=10, end=40),
            _span("1.2", parent="1", start=50, end=70),
        ),
    )

    assert trace.self_time("1") == 50
    assert trace.self_time("1.1") == 30


def test_self_time_is_floored_at_zero_when_children_overlap():
    """A clock that moved backwards, or two children measured across a
    boundary. A negative share of the time is not a fact about anything."""
    trace = Trace(
        trace_id="t",
        spans=(
            _span("1", start=0, end=10),
            _span("1.1", parent="1", start=0, end=9),
            _span("1.2", parent="1", start=0, end=9),
        ),
    )

    assert trace.self_time("1") == 0


def test_an_unfinished_span_has_no_self_time():
    trace = Trace(trace_id="t", spans=(_span("1", end=None),))

    assert trace.self_time("1") is None


def test_self_time_of_something_that_is_not_in_the_trace_is_none():
    assert Trace(trace_id="t", spans=(_span("1"),)).self_time("nope") is None


def test_totals_are_reported_per_kind():
    trace = Trace(
        trace_id="t",
        spans=(
            _span("1", start=0, end=100, kind=SpanKind.REVIEW),
            _span("1.1", parent="1", start=0, end=30, kind=SpanKind.TOOL),
            _span("1.2", parent="1", start=30, end=60, kind=SpanKind.TOOL),
            _span("1.3", parent="1", start=60, end=70, kind=SpanKind.MODEL),
        ),
    )

    assert trace.by_kind[SpanKind.TOOL] == 60
    assert trace.by_kind[SpanKind.MODEL] == 10
    assert trace.by_kind[SpanKind.REVIEW] == 30


@given(st.lists(st.tuples(st.integers(0, 40), st.integers(1, 20)), min_size=1, max_size=6))
def test_the_self_times_never_exceed_the_root(children):
    root = _span("1", start=0, end=200, kind=SpanKind.REVIEW)
    spans = [root] + [
        _span(f"1.{index}", parent="1", start=min(start, 190), end=min(start + length, 200))
        for index, (start, length) in enumerate(children)
    ]
    trace = Trace(trace_id="t", spans=tuple(spans))

    assert sum(trace.by_kind.values()) <= root.duration_ms


def test_the_critical_path_is_the_longest_chain():
    trace = Trace(
        trace_id="t",
        spans=(
            _span("1", start=0, end=100, kind=SpanKind.REVIEW),
            _span("1.1", parent="1", start=0, end=90),
            _span("1.2", parent="1", start=90, end=95),
            _span("1.1.1", parent="1.1", start=0, end=80),
        ),
    )

    assert [span.span_id for span in trace.critical_path] == ["1", "1.1", "1.1.1"]


def test_the_critical_path_is_deterministic_on_a_tie():
    trace = Trace(
        trace_id="t",
        spans=(
            _span("1", start=0, end=100),
            _span("1.b", parent="1", start=0, end=50),
            _span("1.a", parent="1", start=0, end=50),
        ),
    )

    assert [span.span_id for span in trace.critical_path] == ["1", "1.a"]


def test_the_critical_path_of_an_empty_trace_is_empty():
    assert Trace(trace_id="t", spans=()).critical_path == ()


def test_the_duration_of_a_trace_is_its_roots():
    trace = Trace(trace_id="t", spans=(_span("1", start=5, end=105),))

    assert trace.duration_ms == 100


def test_the_duration_of_an_empty_trace_is_none():
    assert Trace(trace_id="t", spans=()).duration_ms is None


def test_a_trace_knows_how_many_spans_it_holds():
    trace = Trace(trace_id="t", spans=(_span("1"), _span("1.1", parent="1")))

    assert len(trace) == 2


@pytest.mark.parametrize("kind", list(SpanKind))
def test_every_kind_can_be_totalled(kind):
    trace = Trace(trace_id="t", spans=(_span("1", start=0, end=10, kind=kind),))

    assert trace.by_kind[kind] == 10
