"""Steps 1–3 — who made a claim, what a run was, and the one invariant."""

import pytest

from code_reviewer.domain.provenance import (
    FINGERPRINT_LENGTH,
    AgentCost,
    DecisionRecord,
    Producer,
    ProducerKind,
    Provenance,
    RunIdentity,
    SuppressionRecord,
    deterministic_only,
    fingerprint,
)

ANALYZER = Producer(ProducerKind.ANALYZER, "SASTAnalyzer", "2.13.0")
AGENT = Producer(ProducerKind.AGENT, "security", "2.13.0")
TOOL = Producer(ProducerKind.TOOL, "workspace", "2.13.0")


def _claim(producer: Producer = ANALYZER, rule_id: str = "SAST.SQL_INJECTION") -> Provenance:
    return Provenance(
        producer=producer,
        rule_id=rule_id,
        location="storage/repository.py:11",
        severity="critical",
        evidence=("auth/tokens.py:1-4", "1.1.3"),
    )


def _identity(**overrides) -> RunIdentity:
    defaults = {
        "package_version": "2.13.0",
        "policy_version": "1.0",
        "model": "qwen3-8b",
        "prompt_fingerprint": "abc123def456",
        "ruleset_version": "2.13.0",
        "evaluation_baseline": "precision 1.00 / recall 1.00 / f1 1.00",
    }
    return RunIdentity(**{**defaults, **overrides})


# -- producers ---------------------------------------------------------------


def test_a_producer_carries_kind_name_and_version():
    assert ANALYZER.kind is ProducerKind.ANALYZER
    assert ANALYZER.name == "SASTAnalyzer"
    assert str(ANALYZER) == "analyzer:SASTAnalyzer@2.13.0"


def test_a_producer_without_a_name_is_refused():
    """'Something produced this' is not provenance."""
    with pytest.raises(ValueError):
        Producer(ProducerKind.ANALYZER, "  ")


def test_an_analyzer_and_a_tool_are_deterministic_and_an_agent_is_not():
    assert ANALYZER.is_deterministic
    assert TOOL.is_deterministic
    assert not AGENT.is_deterministic


def test_a_claim_carries_the_evidence_it_rested_on():
    claim = _claim()

    assert claim.evidence == ("auth/tokens.py:1-4", "1.1.3")
    assert claim.is_deterministic


def test_deterministic_only_filters_out_opinions():
    assert deterministic_only([_claim(), _claim(AGENT), _claim(TOOL)]) == (
        _claim(),
        _claim(TOOL),
    )


# -- the run's identity ------------------------------------------------------


def test_an_identity_records_every_version_that_produced_the_review():
    identity = _identity()

    assert identity.package_version == "2.13.0"
    assert identity.policy_version == "1.0"
    assert identity.model == "qwen3-8b"
    assert identity.prompt_fingerprint
    assert identity.ruleset_version
    assert identity.evaluation_baseline


def test_no_model_is_recorded_as_none_rather_than_omitted():
    """'This review had no model' is a fact about it, and a missing field
    reads as an oversight."""
    assert _identity(model="").model == "none"


def test_an_identity_without_a_package_version_is_refused():
    with pytest.raises(ValueError):
        RunIdentity(package_version="", policy_version="1.0")


def test_two_different_prompts_fingerprint_differently():
    assert fingerprint("you are a reviewer") != fingerprint("you are a security reviewer")


def test_the_same_prompts_fingerprint_the_same_way():
    assert fingerprint("a", "b") == fingerprint("a", "b")


def test_the_order_of_the_prompts_matters():
    """Four specialists' prompts are four prompts, not a set."""
    assert fingerprint("a", "b") != fingerprint("b", "a")


def test_a_fingerprint_is_short_enough_to_read_out():
    assert len(fingerprint("anything")) == FINGERPRINT_LENGTH


def test_the_fingerprint_is_stable_across_processes():
    """Asserted against a literal, so changing the hashing is a change
    somebody has to make deliberately."""
    assert fingerprint("code-reviewer") == "b6b17025f0c5"


# -- the record --------------------------------------------------------------


def _record(**overrides) -> DecisionRecord:
    defaults = {"verdict": "pass", "exit_code": 0, "identity": _identity()}
    return DecisionRecord(**{**defaults, **overrides})


def test_a_passing_record_needs_no_blocking_findings():
    record = _record()

    assert not record.is_blocking
    assert "nothing blocked" in record.summary()


def test_a_blocking_record_citing_analyzers_is_accepted():
    record = _record(verdict="fail", exit_code=1, blocking=(_claim(),), findings=(_claim(),))

    assert record.is_blocking
    assert record.deciders == ("analyzer:SASTAnalyzer@2.13.0",)
    assert "blocked by" in record.summary()


def test_a_blocking_record_citing_a_tool_is_accepted():
    """A refused file read is a fact about the request, not a model's
    opinion — which is why it has been a CRITICAL finding since Level 8."""
    record = _record(verdict="fail", exit_code=1, blocking=(_claim(TOOL, "SANDBOX.VIOLATION"),))

    assert record.is_blocking


def test_a_blocking_record_citing_a_model_is_refused():
    """The invariant this level exists for. ADR 0004 says the gate decides
    from findings and never from prose; here that stops being a design rule
    and becomes something a record cannot violate."""
    with pytest.raises(ValueError) as error:
        _record(verdict="fail", exit_code=1, blocking=(_claim(AGENT),))

    assert "may not rest on a model's opinion" in str(error.value)
    assert "SAST.SQL_INJECTION" in str(error.value)
    assert "agent:security" in str(error.value)
    assert "ADR 0004" in str(error.value)


def test_one_model_claim_among_several_is_enough_to_refuse():
    with pytest.raises(ValueError):
        _record(
            verdict="fail",
            exit_code=1,
            blocking=(_claim(), _claim(AGENT, "AGENT.OPINION"), _claim(TOOL)),
        )


def test_a_non_blocking_record_may_cite_anything():
    """An agent's prose is allowed to warn, which is exactly what ADR 0004
    says: findings block, prose warns."""
    record = _record(verdict="warn", findings=(_claim(AGENT),))

    assert not record.is_blocking


def test_a_blocking_verdict_with_nothing_blocking_is_refused():
    """Something decided, and a record that cannot say what is not a
    record."""
    with pytest.raises(ValueError):
        _record(verdict="fail", exit_code=1)


# -- the rest of the record --------------------------------------------------


def test_suppressions_are_part_of_the_record():
    """A governance record that omits what was silenced can be gamed by
    silencing things."""
    record = _record(
        suppressions=(
            SuppressionRecord("SAST.WEAK_CRYPTO", "cache/keys.py:4", "md5 is a cache key here"),
            SuppressionRecord("QUALITY.DRY", "generated.py:1"),
        )
    )

    assert len(record.suppressions) == 2
    assert [item.rule_id for item in record.unexplained_suppressions] == ["QUALITY.DRY"]


def test_per_agent_cost_is_part_of_the_record():
    record = _record(
        agent_costs=(AgentCost(agent="security", runs=1, tool_calls=3, tokens_allowed=4000),)
    )

    assert record.agent_costs[0].tool_calls == 3


def test_a_review_that_did_not_complete_still_produces_a_record():
    """A missing file is indistinguishable from a review nobody ran."""
    record = _record(completed=False, failure_reason="ForgeError: 502")

    assert "not completed" in record.summary()
    assert "502" in record.summary()


def test_a_record_is_a_value():
    assert _record() == _record()
