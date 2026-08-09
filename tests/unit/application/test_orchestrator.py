"""Step 6 — the committee, and what happens when part of it falls over."""

import pytest

from code_reviewer.application.orchestration_service import ReviewOrchestrator
from code_reviewer.application.ports import ReviewBrief, Reviewer, Specialist
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.orchestration import AgentReport, Handoff, Specialism
from code_reviewer.domain.severity import Severity


def _finding(category=FindingCategory.SECURITY) -> Finding:
    return Finding(
        category=category,
        severity=Severity.HIGH,
        file_path="src/app.py",
        line_number=1,
        title="t",
        description="d",
        remediation="r",
        rule_id="X.Y",
    )


def _brief(**overrides) -> ReviewBrief:
    return ReviewBrief(**{"file_path": "src/app.py", "diff": "+x = 1", **overrides})


class ScriptedSpecialist(Specialist):
    """Returns a canned report, and records what it was asked."""

    def __init__(self, prose="text", handoffs=(), error=None, tool_calls=0):
        self.prose = prose
        self.handoffs = tuple(handoffs)
        self.error = error
        self.tool_calls = tool_calls
        self.assignments = []

    def review(self, brief, assignment):
        self.assignments.append(assignment)
        if self.error is not None:
            raise self.error
        return AgentReport(
            specialism=assignment.specialism,
            prose=f"{assignment.specialism.value}: {self.prose}",
            tokens_allowed=assignment.token_budget,
            tool_calls=self.tool_calls,
            handoffs=self.handoffs,
        )


def _orchestrator(**specialists) -> tuple[ReviewOrchestrator, dict]:
    registry = {Specialism(name): agent for name, agent in specialists.items()}
    return ReviewOrchestrator(registry), registry


# -- the shape of it ---------------------------------------------------------


def test_the_orchestrator_is_a_reviewer():
    orchestrator, _ = _orchestrator(architecture=ScriptedSpecialist())

    assert isinstance(orchestrator, Reviewer)


def test_the_generalist_runs_on_a_file_with_no_findings():
    orchestrator, registry = _orchestrator(architecture=ScriptedSpecialist(), security=ScriptedSpecialist())

    document = orchestrator.review_diff(_brief())

    assert len(registry[Specialism.ARCHITECTURE].assignments) == 1
    assert registry[Specialism.SECURITY].assignments == []
    assert "architecture: text" in document


def test_a_security_finding_brings_in_the_security_specialist():
    orchestrator, registry = _orchestrator(architecture=ScriptedSpecialist(), security=ScriptedSpecialist())

    document = orchestrator.review_diff(_brief(findings=(_finding(),)))

    assert len(registry[Specialism.SECURITY].assignments) == 1
    assert "security: text" in document


def test_a_manifest_brings_in_the_dependency_specialist():
    orchestrator, registry = _orchestrator(architecture=ScriptedSpecialist(), dependency=ScriptedSpecialist())

    orchestrator.review_diff(ReviewBrief(file_path="pyproject.toml", diff="+dep = 1"))

    assert len(registry[Specialism.DEPENDENCY].assignments) == 1


def test_each_specialist_is_given_its_own_budget():
    orchestrator, registry = _orchestrator(architecture=ScriptedSpecialist(), security=ScriptedSpecialist())

    orchestrator.review_diff(_brief(findings=(_finding(),)))

    architecture = registry[Specialism.ARCHITECTURE].assignments[0].token_budget
    security = registry[Specialism.SECURITY].assignments[0].token_budget
    assert security > architecture > 0


def test_the_brief_reaches_every_specialist_whole():
    """Retrieved code and recalled memory are not the generalist's privilege."""
    orchestrator, registry = _orchestrator(architecture=ScriptedSpecialist(), security=ScriptedSpecialist())
    brief = _brief(findings=(_finding(),), other_files=("a.py",))

    orchestrator.review_diff(brief)

    for specialism in (Specialism.ARCHITECTURE, Specialism.SECURITY):
        assert registry[specialism].assignments


# -- failure -----------------------------------------------------------------


def test_a_failing_specialist_costs_one_section_and_no_more():
    orchestrator, _ = _orchestrator(
        architecture=ScriptedSpecialist(),
        security=ScriptedSpecialist(error=RuntimeError("the endpoint timed out")),
    )

    document = orchestrator.review_diff(_brief(findings=(_finding(),)))

    assert "architecture: text" in document
    assert "did not complete" in document
    assert "the endpoint timed out" in document


def test_every_specialist_failing_still_produces_a_document():
    orchestrator, _ = _orchestrator(
        architecture=ScriptedSpecialist(error=RuntimeError("a")),
        security=ScriptedSpecialist(error=RuntimeError("b")),
    )

    document = orchestrator.review_diff(_brief(findings=(_finding(),)))

    assert "did not complete" in document
    assert document.strip()


def test_an_unregistered_specialism_is_skipped_with_a_stated_reason():
    """A composition root that forgot to wire one should produce a legible
    report, not a crash."""
    orchestrator, _ = _orchestrator(architecture=ScriptedSpecialist())

    document = orchestrator.review_diff(_brief(findings=(_finding(),)))

    assert "skipped" in document
    assert "no specialist is registered" in document


def test_a_committee_with_nobody_registered_says_so():
    document = ReviewOrchestrator({}).review_diff(_brief())

    assert "No agent produced a review" in document


# -- handoff -----------------------------------------------------------------


def test_an_accepted_handoff_runs_the_target_once():
    orchestrator, registry = _orchestrator(
        architecture=ScriptedSpecialist(handoffs=[Handoff("dependency", "it comes from a package")]),
        dependency=ScriptedSpecialist(),
    )

    document = orchestrator.review_diff(_brief())

    assert len(registry[Specialism.DEPENDENCY].assignments) == 1
    assert "dependency: text" in document


def test_a_handed_to_specialist_is_told_who_asked_and_why():
    orchestrator, registry = _orchestrator(
        architecture=ScriptedSpecialist(handoffs=[Handoff("dependency", "it comes from a package")]),
        dependency=ScriptedSpecialist(),
    )

    orchestrator.review_diff(_brief())

    assignment = registry[Specialism.DEPENDENCY].assignments[0]
    assert assignment.handed_from is Specialism.ARCHITECTURE
    assert "comes from a package" in assignment.handoff_reason


def test_a_handoff_to_a_specialist_that_already_ran_is_refused_and_stated():
    orchestrator, registry = _orchestrator(
        architecture=ScriptedSpecialist(handoffs=[Handoff("security", "another look")]),
        security=ScriptedSpecialist(),
    )

    document = orchestrator.review_diff(_brief(findings=(_finding(),)))

    assert len(registry[Specialism.SECURITY].assignments) == 1
    assert "handoff refused" in document
    assert "already run" in document


def test_a_handed_to_specialist_cannot_hand_on_again():
    """Depth one, structurally: the second round is run at a depth where the
    domain refuses everything."""
    orchestrator, registry = _orchestrator(
        architecture=ScriptedSpecialist(handoffs=[Handoff("dependency", "look")]),
        dependency=ScriptedSpecialist(handoffs=[Handoff("performance", "and this")]),
        performance=ScriptedSpecialist(),
    )

    orchestrator.review_diff(_brief())

    assert registry[Specialism.PERFORMANCE].assignments == []


def test_a_handoff_to_something_that_is_not_a_specialism_is_refused_and_stated():
    orchestrator, _ = _orchestrator(
        architecture=ScriptedSpecialist(handoffs=[Handoff("database-administrator", "?")])
    )

    document = orchestrator.review_diff(_brief())

    assert "handoff refused" in document
    assert "not a specialism" in document


def test_a_handoff_gets_a_budget_of_its_own():
    orchestrator, registry = _orchestrator(
        architecture=ScriptedSpecialist(handoffs=[Handoff("dependency", "look")]),
        dependency=ScriptedSpecialist(),
    )

    orchestrator.review_diff(_brief())

    assert registry[Specialism.DEPENDENCY].assignments[0].token_budget > 0


# -- accounting --------------------------------------------------------------


def test_the_footer_names_every_agent_and_what_it_cost():
    orchestrator, _ = _orchestrator(
        architecture=ScriptedSpecialist(tool_calls=2), security=ScriptedSpecialist(tool_calls=5)
    )

    document = orchestrator.review_diff(_brief(findings=(_finding(),)))

    assert "Review agents" in document
    assert "| architecture |" in document
    assert "| security |" in document
    assert "| 5 |" in document


def test_the_outcome_is_readable_afterwards():
    orchestrator, _ = _orchestrator(
        architecture=ScriptedSpecialist(tool_calls=2), security=ScriptedSpecialist(tool_calls=5)
    )

    orchestrator.review_diff(_brief(findings=(_finding(),)))

    outcome = orchestrator.last_outcome
    assert {report.specialism for report in outcome.reports} == {
        Specialism.ARCHITECTURE,
        Specialism.SECURITY,
    }
    assert outcome.tool_calls == 7
    assert outcome.failures == ()


def test_the_outcome_is_replaced_per_file_rather_than_accumulated():
    orchestrator, _ = _orchestrator(architecture=ScriptedSpecialist())

    orchestrator.review_diff(_brief())
    orchestrator.review_diff(_brief(file_path="other.py"))

    assert len(orchestrator.last_outcome.reports) == 1


def test_a_tiny_budget_still_gives_everyone_something():
    """A misconfiguration should degrade, not divide by zero."""
    orchestrator = ReviewOrchestrator(
        {specialism: ScriptedSpecialist() for specialism in Specialism}, total_budget=8
    )

    document = orchestrator.review_diff(
        _brief(
            findings=(
                _finding(FindingCategory.SECURITY),
                _finding(FindingCategory.PERFORMANCE),
                _finding(FindingCategory.DEPENDENCY),
            )
        )
    )

    assert "architecture" in document


def test_sections_are_ordered_however_the_agents_were_registered():
    orchestrator = ReviewOrchestrator(
        {
            Specialism.DEPENDENCY: ScriptedSpecialist(),
            Specialism.SECURITY: ScriptedSpecialist(),
            Specialism.ARCHITECTURE: ScriptedSpecialist(),
        }
    )

    document = orchestrator.review_diff(
        _brief(findings=(_finding(FindingCategory.SECURITY), _finding(FindingCategory.DEPENDENCY)))
    )

    assert document.index("architecture: text") < document.index("security: text")
    assert document.index("security: text") < document.index("dependency: text")


def test_the_same_inputs_produce_the_same_document():
    def build():
        return ReviewOrchestrator({specialism: ScriptedSpecialist() for specialism in Specialism})

    brief = _brief(findings=(_finding(),))

    assert build().review_diff(brief) == build().review_diff(brief)


@pytest.mark.parametrize("path", ["src/app.py", "pyproject.toml", "package-lock.json"])
def test_no_input_makes_the_committee_run_more_than_twice_per_specialism(path):
    """AC-13 at the orchestrator: whatever the agents ask for, the number of
    invocations for one file is bounded."""
    greedy = {
        specialism: ScriptedSpecialist(handoffs=[Handoff(other.value, "more") for other in Specialism])
        for specialism in Specialism
    }
    ReviewOrchestrator(greedy).review_diff(
        ReviewBrief(
            file_path=path,
            diff="+x",
            findings=tuple(_finding(category) for category in FindingCategory),
        )
    )

    for specialism, agent in greedy.items():
        assert len(agent.assignments) <= 1, specialism
