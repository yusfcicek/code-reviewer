"""Steps 1–3 — what a specialism is, who reviews what, and for how much."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.orchestration import (
    COMPOSITION_ORDER,
    SPECIALIST_TOOLS,
    SPECIALIST_WEIGHTS,
    Specialism,
    is_manifest_path,
    plan_assignments,
    split_budget,
)
from code_reviewer.domain.severity import Severity


def _finding(category: FindingCategory, rule_id="X.Y") -> Finding:
    return Finding(
        category=category,
        severity=Severity.HIGH,
        file_path="src/app.py",
        line_number=3,
        title="t",
        description="d",
        remediation="r",
        rule_id=rule_id,
    )


# -- the specialisms ---------------------------------------------------------


def test_there_is_one_weight_and_one_tool_set_per_specialism():
    assert set(SPECIALIST_WEIGHTS) == set(Specialism)
    assert set(SPECIALIST_TOOLS) == set(Specialism)


def test_every_weight_is_positive():
    assert all(weight > 0 for weight in SPECIALIST_WEIGHTS.values())


def test_security_is_worth_more_of_the_budget_than_anything_else():
    """The spec says budget must be spendable where it matters. A table that
    does not say so is a table nobody checked."""
    assert SPECIALIST_WEIGHTS[Specialism.SECURITY] == max(SPECIALIST_WEIGHTS.values())
    assert SPECIALIST_WEIGHTS[Specialism.SECURITY] > SPECIALIST_WEIGHTS[Specialism.ARCHITECTURE]


def test_the_composition_order_covers_every_specialism_exactly_once():
    assert sorted(COMPOSITION_ORDER, key=lambda item: item.value) == sorted(
        Specialism, key=lambda item: item.value
    )


def test_the_generalist_comes_first_in_the_composition():
    assert COMPOSITION_ORDER[0] is Specialism.ARCHITECTURE


def test_every_specialist_can_read_a_file_and_search_the_repository():
    for specialism, tools in SPECIALIST_TOOLS.items():
        assert "read_file" in tools, specialism
        assert "search_related_code" in tools, specialism


def test_the_scanning_tools_belong_to_exactly_one_specialism_each():
    """Asserted explicitly rather than derived, so a later edit that widens a
    tool set shows up in a diff as a changed expectation."""
    owners = {
        "run_sast_scan": Specialism.SECURITY,
        "analyze_performance": Specialism.PERFORMANCE,
        "run_semantic_analysis": Specialism.ARCHITECTURE,
        "find_ripple_effects": Specialism.DEPENDENCY,
    }

    for tool, owner in owners.items():
        holders = {specialism for specialism, tools in SPECIALIST_TOOLS.items() if tool in tools}
        assert holders == {owner}, f"{tool} is offered to {holders}"


def test_no_specialism_is_offered_a_tool_that_does_not_exist():
    from code_reviewer.infrastructure.tools import get_tools

    available = {tool.name for tool in get_tools()}
    for specialism, tools in SPECIALIST_TOOLS.items():
        assert set(tools) <= available, f"{specialism} names unknown tools: {set(tools) - available}"


# -- assignment --------------------------------------------------------------


def test_every_reviewed_file_gets_the_generalist():
    assert plan_assignments([], is_manifest=False) == (Specialism.ARCHITECTURE,)


def test_a_security_finding_assigns_the_security_specialist():
    plan = plan_assignments([_finding(FindingCategory.SECURITY)], is_manifest=False)

    assert Specialism.SECURITY in plan


def test_a_performance_finding_assigns_the_performance_specialist():
    plan = plan_assignments([_finding(FindingCategory.PERFORMANCE)], is_manifest=False)

    assert Specialism.PERFORMANCE in plan


def test_a_dependency_finding_assigns_the_dependency_specialist():
    plan = plan_assignments([_finding(FindingCategory.DEPENDENCY)], is_manifest=False)

    assert Specialism.DEPENDENCY in plan


def test_a_manifest_assigns_the_dependency_specialist_with_no_findings_at_all():
    """The file *is* the evidence. A lock file with nothing reported in it is
    still the artefact that records a changed transitive dependency."""
    plan = plan_assignments([], is_manifest=True)

    assert Specialism.DEPENDENCY in plan


def test_a_quality_finding_assigns_nobody_new():
    """Quality is the generalist's own subject."""
    assert plan_assignments([_finding(FindingCategory.QUALITY)], is_manifest=False) == (
        Specialism.ARCHITECTURE,
    )


def test_two_security_findings_assign_one_security_specialist():
    plan = plan_assignments(
        [_finding(FindingCategory.SECURITY), _finding(FindingCategory.SECURITY)], is_manifest=False
    )

    assert plan.count(Specialism.SECURITY) == 1


def test_the_plan_is_ordered_and_a_tuple():
    plan = plan_assignments(
        [_finding(FindingCategory.DEPENDENCY), _finding(FindingCategory.SECURITY)], is_manifest=False
    )

    assert isinstance(plan, tuple)
    assert plan == (Specialism.ARCHITECTURE, Specialism.SECURITY, Specialism.DEPENDENCY)


def test_a_manifest_path_is_recognised():
    assert is_manifest_path("services/api/package-lock.json")
    assert is_manifest_path("pyproject.toml")
    assert not is_manifest_path("src/app.py")


# -- the budget --------------------------------------------------------------


def test_the_split_sums_to_the_total():
    plan = (Specialism.ARCHITECTURE, Specialism.SECURITY, Specialism.DEPENDENCY)

    shares = split_budget(1000, plan)

    assert sum(shares.values()) == 1000
    assert set(shares) == set(plan)


def test_security_gets_more_than_the_generalist():
    shares = split_budget(1000, (Specialism.ARCHITECTURE, Specialism.SECURITY))

    assert shares[Specialism.SECURITY] > shares[Specialism.ARCHITECTURE]


def test_nobody_assigned_gets_zero_even_when_the_budget_is_tiny():
    plan = tuple(Specialism)

    shares = split_budget(len(plan), plan)

    assert sorted(shares.values()) == [1, 1, 1, 1]


def test_a_remainder_goes_somewhere_rather_than_being_dropped():
    """A split that loses tokens is a split somebody debugs on a Friday."""
    plan = (Specialism.ARCHITECTURE, Specialism.SECURITY, Specialism.PERFORMANCE)

    assert sum(split_budget(1001, plan).values()) == 1001


def test_a_budget_smaller_than_the_team_is_refused():
    with pytest.raises(ValueError):
        split_budget(2, tuple(Specialism))


def test_splitting_between_nobody_is_refused():
    with pytest.raises(ValueError):
        split_budget(100, ())


@given(
    st.integers(min_value=1, max_value=4),
    st.integers(min_value=4, max_value=200_000),
)
def test_every_share_is_at_least_one_and_the_shares_sum_to_the_total(count, total):
    plan = tuple(COMPOSITION_ORDER[:count])

    shares = split_budget(total, plan)

    assert sum(shares.values()) == total
    assert all(share >= 1 for share in shares.values())
    assert set(shares) == set(plan)


@given(st.integers(min_value=100, max_value=100_000))
def test_the_split_is_deterministic(total):
    plan = (Specialism.ARCHITECTURE, Specialism.SECURITY, Specialism.PERFORMANCE)

    assert split_budget(total, plan) == split_budget(total, tuple(reversed(plan)))
