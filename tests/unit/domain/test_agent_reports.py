"""Steps 4–5 — what an agent reports, how it composes, and the handoff rule."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.orchestration import (
    AgentReport,
    Handoff,
    Specialism,
    accept_handoffs,
    compose,
)

_NAMES = [specialism.value for specialism in Specialism] + ["", "orchestrator", "SECURITY "]


def _report(specialism: Specialism, prose: str = "text") -> AgentReport:
    return AgentReport(specialism=specialism, prose=prose)


# -- the report --------------------------------------------------------------


def test_a_report_carries_its_specialism_and_its_cost():
    report = AgentReport(specialism=Specialism.SECURITY, prose="found it", tokens_allowed=800, tool_calls=3)

    assert report.specialism is Specialism.SECURITY
    assert report.succeeded
    assert report.tokens_allowed == 800
    assert report.tool_calls == 3


def test_a_failed_report_carries_a_reason_and_no_prose():
    report = AgentReport.failed(Specialism.PERFORMANCE, "the loop ran out of iterations")

    assert not report.succeeded
    assert report.prose == ""
    assert "iterations" in report.failure_reason


def test_a_failure_without_a_reason_is_refused():
    """A section that says 'this agent failed' and nothing else is a section
    nobody can act on."""
    with pytest.raises(ValueError):
        AgentReport(specialism=Specialism.SECURITY, succeeded=False)


# -- composition -------------------------------------------------------------


def test_sections_appear_in_the_fixed_order_whatever_order_they_arrived_in():
    shuffled = [
        _report(Specialism.DEPENDENCY, "deps"),
        _report(Specialism.SECURITY, "sec"),
        _report(Specialism.ARCHITECTURE, "arch"),
        _report(Specialism.PERFORMANCE, "perf"),
    ]

    document = compose(shuffled)

    assert document.index("arch") < document.index("sec") < document.index("perf") < document.index("deps")


def test_every_section_is_attributed():
    """An unattributed paragraph is the thing multi-agent review exists to
    stop producing."""
    document = compose([_report(Specialism.SECURITY, "sec")])

    assert "Security" in document
    assert "sec" in document


def test_a_failed_specialist_is_stated_rather_than_omitted():
    document = compose(
        [
            _report(Specialism.ARCHITECTURE, "arch"),
            AgentReport.failed(Specialism.SECURITY, "the endpoint timed out"),
        ]
    )

    assert "arch" in document
    assert "Security" in document
    assert "the endpoint timed out" in document
    assert "did not complete" in document


def test_every_specialist_failing_still_composes_a_document():
    document = compose(
        [
            AgentReport.failed(Specialism.ARCHITECTURE, "a"),
            AgentReport.failed(Specialism.SECURITY, "b"),
        ]
    )

    assert "did not complete" in document
    assert document.strip()


def test_composing_nothing_says_so_rather_than_returning_an_empty_string():
    """An empty review reads as an approval. It is not one."""
    document = compose([])

    assert "no agent" in document.lower()
    assert document.strip()


def test_composition_is_stable():
    reports = [_report(Specialism.SECURITY, "sec"), _report(Specialism.ARCHITECTURE, "arch")]

    assert compose(reports) == compose(list(reversed(reports)))


def test_a_successful_report_with_nothing_to_say_is_stated():
    document = compose([AgentReport(specialism=Specialism.SECURITY, prose="   ")])

    assert "nothing to report" in document.lower()


# -- handoff -----------------------------------------------------------------


def test_a_handoff_to_an_unrun_specialism_is_accepted():
    decision = accept_handoffs(
        [Handoff(target="dependency", reason="the call comes from a package")],
        already_run={Specialism.SECURITY},
        depth=0,
    )

    assert decision.accepted == (Specialism.DEPENDENCY,)
    assert decision.refused == ()


def test_a_handoff_to_a_specialism_already_run_is_refused_and_recorded():
    decision = accept_handoffs(
        [Handoff(target="security", reason="worth a second look")],
        already_run={Specialism.SECURITY},
        depth=0,
    )

    assert decision.accepted == ()
    assert len(decision.refused) == 1
    assert "already" in decision.refused[0][1]


def test_a_handoff_at_depth_one_is_refused_whatever_it_asks_for():
    """The depth is structural, not a counter. A depth that is a number is a
    depth somebody eventually raises (decision D-3)."""
    decision = accept_handoffs([Handoff(target="dependency", reason="please")], already_run=set(), depth=1)

    assert decision.accepted == ()
    assert "once" in decision.refused[0][1]


def test_a_handoff_to_something_that_is_not_a_specialism_is_refused_and_recorded():
    decision = accept_handoffs(
        [Handoff(target="database-administrator", reason="?")], already_run=set(), depth=0
    )

    assert decision.accepted == ()
    assert "database-administrator" in decision.refused[0][0]
    assert "not a specialism" in decision.refused[0][1]


def test_a_target_is_matched_case_insensitively_and_without_surrounding_space():
    decision = accept_handoffs([Handoff(target="  SECURITY ")], already_run=set(), depth=0)

    assert decision.accepted == (Specialism.SECURITY,)


def test_two_requests_for_one_specialism_accept_it_once():
    decision = accept_handoffs(
        [Handoff(target="security"), Handoff(target="security")], already_run=set(), depth=0
    )

    assert decision.accepted == (Specialism.SECURITY,)


def test_the_accepted_set_is_ordered_by_the_composition_order():
    decision = accept_handoffs(
        [Handoff(target="dependency"), Handoff(target="security")], already_run=set(), depth=0
    )

    assert decision.accepted == (Specialism.SECURITY, Specialism.DEPENDENCY)


def test_no_requests_accepts_nothing_and_refuses_nothing():
    decision = accept_handoffs([], already_run=set(), depth=0)

    assert decision.accepted == ()
    assert decision.refused == ()


@given(
    st.lists(st.sampled_from(_NAMES), max_size=12),
    st.sets(st.sampled_from(list(Specialism)), max_size=4),
    st.integers(min_value=0, max_value=3),
)
def test_a_handoff_can_never_produce_an_unbounded_run(targets, already_run, depth):
    """AC-13. Whatever is asked for, the accepted set is disjoint from what has
    already run and no larger than the number of specialisms — so the total
    number of agent invocations for one file is bounded by 2 × len(Specialism)
    regardless of what any model says."""
    decision = accept_handoffs([Handoff(target=name) for name in targets], already_run, depth)

    assert set(decision.accepted).isdisjoint(already_run)
    assert len(decision.accepted) <= len(Specialism)
    assert len(set(decision.accepted)) == len(decision.accepted)
    if depth > 0:
        assert decision.accepted == ()
