"""Step 7 — one agent with one subject, one catalogue and one budget."""

from unittest.mock import MagicMock

import pytest

from code_reviewer.application.ports import LLMProvider, MemoryStrategy, ReviewBrief
from code_reviewer.domain.orchestration import Assignment, Specialism
from code_reviewer.infrastructure.llm.specialist_agent import (
    MIN_ITERATIONS,
    SpecialistAgent,
    parse_handoffs,
    system_prompt_for,
    tools_for,
)
from tests.fakes.scripted_model import ScriptedChatModel


def _memory():
    memory = MagicMock(spec=MemoryStrategy)
    memory.load_context.return_value = ""
    return memory


class _Provider(LLMProvider):
    def __init__(self, model):
        self._model = model

    def get_chat_model(self):
        return self._model


def _agent(specialism: Specialism, responses) -> SpecialistAgent:
    return SpecialistAgent(
        specialism,
        _Provider(ScriptedChatModel(responses)),
        _memory(),
        tool_protocol="hermes",
    )


def _brief() -> ReviewBrief:
    return ReviewBrief(file_path="src/app.py", diff="+x = 1")


# -- the catalogue -----------------------------------------------------------


def test_a_specialist_is_offered_only_its_own_tools():
    names = {tool.name for tool in tools_for(Specialism.SECURITY)}

    assert "run_sast_scan" in names
    assert "analyze_performance" not in names
    assert "find_ripple_effects" not in names


def test_every_specialist_can_still_read_and_search():
    for specialism in Specialism:
        names = {tool.name for tool in tools_for(specialism)}
        assert "read_file" in names, specialism
        assert "search_related_code" in names, specialism


def test_the_agent_binds_the_narrowed_catalogue():
    agent = _agent(Specialism.SECURITY, ["## Done"])

    assert {tool.name for tool in agent._agent.tools} == {
        tool.name for tool in tools_for(Specialism.SECURITY)
    }


# -- the prompt --------------------------------------------------------------


@pytest.mark.parametrize("specialism", list(Specialism))
def test_every_specialism_inherits_the_trust_boundary(specialism):
    """It is not something one of four agents may forget."""
    prompt = system_prompt_for(specialism)

    assert "TRUST BOUNDARY" in prompt
    assert "untrusted_diff" in prompt


@pytest.mark.parametrize("specialism", list(Specialism))
def test_every_specialism_names_itself(specialism):
    assert specialism.value.upper() in system_prompt_for(specialism)


def test_a_specialist_is_told_to_stay_in_its_lane():
    assert "Say nothing about style or performance" in system_prompt_for(Specialism.SECURITY)


def test_the_generalist_is_told_it_owns_the_summary():
    assert "summary" in system_prompt_for(Specialism.ARCHITECTURE)


def test_the_handoff_syntax_is_in_every_prompt():
    for specialism in Specialism:
        assert "HANDOFF:" in system_prompt_for(specialism)


# -- handoff parsing ---------------------------------------------------------


def test_a_handoff_line_is_parsed_and_removed_from_the_prose():
    requests, prose = parse_handoffs(
        "## Security\nThe call is unsafe.\nHANDOFF: dependency - it comes from a package\nDone."
    )

    assert [(item.target, item.reason) for item in requests] == [("dependency", "it comes from a package")]
    assert "HANDOFF" not in prose
    assert "The call is unsafe." in prose


def test_a_response_with_no_handoff_reports_none():
    requests, prose = parse_handoffs("## Security\nNothing to add.")

    assert requests == ()
    assert prose == "## Security\nNothing to add."


def test_a_handoff_without_a_reason_is_still_a_handoff():
    requests, _ = parse_handoffs("HANDOFF: performance")

    assert requests[0].target == "performance"
    assert requests[0].reason == ""


def test_the_word_handoff_in_a_sentence_is_not_a_handoff():
    """The syntax is a line, not a mention. A review discussing handoffs
    should not trigger one."""
    requests, _ = parse_handoffs("I considered a HANDOFF to dependency but it is not needed.")

    assert requests == ()


def test_several_handoffs_are_all_parsed():
    requests, _ = parse_handoffs("HANDOFF: security - a\nHANDOFF: performance - b")

    assert [item.target for item in requests] == ["security", "performance"]


# -- the budget --------------------------------------------------------------


def test_the_budget_becomes_an_iteration_cap():
    agent = _agent(Specialism.SECURITY, ["## Done"])

    agent.review(_brief(), Assignment(Specialism.SECURITY, token_budget=15_000))

    assert agent._agent.loop.max_iterations == 10


def test_a_tiny_budget_still_allows_a_tool_call_and_an_answer():
    agent = _agent(Specialism.SECURITY, ["## Done"])

    agent.review(_brief(), Assignment(Specialism.SECURITY, token_budget=1))

    assert agent._agent.loop.max_iterations == MIN_ITERATIONS


# -- reporting ---------------------------------------------------------------


def test_a_successful_review_reports_its_prose_and_its_budget():
    agent = _agent(Specialism.SECURITY, ["## Security\nLooks fine."])

    report = agent.review(_brief(), Assignment(Specialism.SECURITY, token_budget=4_000))

    assert report.succeeded
    assert report.specialism is Specialism.SECURITY
    assert "Looks fine." in report.prose
    assert report.tokens_allowed == 4_000


def test_a_handoff_in_the_response_reaches_the_report():
    agent = _agent(Specialism.SECURITY, ["## Security\nHANDOFF: dependency - upstream package"])

    report = agent.review(_brief(), Assignment(Specialism.SECURITY, token_budget=4_000))

    assert [item.target for item in report.handoffs] == ["dependency"]


def test_an_agent_that_was_handed_to_cannot_hand_on():
    """Dropped here as well as refused by the orchestrator, so the report does
    not carry a request that was never going to be honoured."""
    agent = _agent(Specialism.DEPENDENCY, ["## Dependencies\nHANDOFF: performance - slow"])

    report = agent.review(
        _brief(),
        Assignment(
            Specialism.DEPENDENCY,
            token_budget=4_000,
            handed_from=Specialism.SECURITY,
            handoff_reason="upstream package",
        ),
    )

    assert report.handoffs == ()


def test_a_handed_to_agent_is_told_who_asked_and_why():
    model = ScriptedChatModel(["## Dependencies\nDone."])
    agent = SpecialistAgent(Specialism.DEPENDENCY, _Provider(model), _memory(), tool_protocol="hermes")

    agent.review(
        _brief(),
        Assignment(
            Specialism.DEPENDENCY,
            token_budget=4_000,
            handed_from=Specialism.SECURITY,
            handoff_reason="upstream package",
        ),
    )

    conversation = "\n".join(str(message.content) for message in model.calls[0])
    assert "[HANDOFF]" in conversation
    assert "upstream package" in conversation


def test_a_model_that_raises_becomes_a_failed_report_rather_than_an_exception():
    agent = _agent(Specialism.SECURITY, [])
    agent._agent.review_diff = _raise

    report = agent.review(_brief(), Assignment(Specialism.SECURITY, token_budget=4_000))

    assert not report.succeeded
    assert "RuntimeError" in report.failure_reason
    assert report.tokens_allowed == 4_000


def _raise(*_args, **_kwargs):
    raise RuntimeError("the endpoint refused the connection")
