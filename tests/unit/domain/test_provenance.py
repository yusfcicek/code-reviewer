"""Steps 1–3 — who made a claim, what a run was, and the one invariant."""

from typing import ClassVar

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
    record = _record(agent_costs=(AgentCost(agent="security", runs=1, tool_calls=3, tokens_allowed=4000),))

    assert record.agent_costs[0].tool_calls == 3


def test_a_review_that_did_not_complete_still_produces_a_record():
    """A missing file is indistinguishable from a review nobody ran."""
    record = _record(completed=False, failure_reason="ForgeError: 502")

    assert "not completed" in record.summary()
    assert "502" in record.summary()


def test_a_record_is_a_value():
    assert _record() == _record()


class TestTheRecordHoldsNoSourceText:
    """Level 30, C-8 — the premise under the refusal to encrypt.

    Level 24 declined to encrypt the record: *"it holds identifiers only, so
    confidentiality is the store's problem and not the format's."* That is the
    right answer while it is true, and until now it was true by habit. Five
    levels have said "identifiers, never content" and nothing checked it on the
    record itself.

    So the refusal gets a test. Every field a `DecisionRecord` can carry is a
    verdict, an identifier, a count, a timestamp or a sentence somebody typed
    into a suppression — and none of them is a line of somebody's source.
    """

    #: What a field may hold. A new field of any other shape is the question
    #: this test exists to force somebody to answer.
    ALLOWED: ClassVar[dict[str, str]] = {
        "verdict": "an enumerated word",
        "exit_code": "a number",
        "identity": "versions, a model name, a fingerprint",
        "project": "an identifier",
        "merge_request": "an identifier",
        "trace_id": "an identifier",
        "findings": "rule ids, paths, line numbers, producers",
        "blocking": "the same",
        "suppressions": "a rule id, a location, and a reason a person typed",
        "agent_costs": "names and token counts",
        "suggestions": "rule ids, paths, line counts",
        "files_considered": "a count",
        "failure_reason": "why a review could not complete",
        "recorded_at": "a timestamp",
        "completed": "a flag",
        "warnings": "what the run could not do",
    }

    @staticmethod
    def _full_record():
        """Every field populated, so nothing escapes by being empty."""
        from code_reviewer.domain.provenance import (
            AgentCost,
            DecisionRecord,
            Producer,
            ProducerKind,
            Provenance,
            RunIdentity,
            SuggestionRecord,
            SuppressionRecord,
        )

        analyzer = Producer(name="sast", kind=ProducerKind.ANALYZER)
        claim = Provenance(
            producer=analyzer,
            rule_id="SAST.SQL_INJECTION",
            location="app.py:12",
            severity="critical",
            evidence=("app.py:12",),
        )
        return DecisionRecord(
            verdict="fail",
            exit_code=1,
            identity=RunIdentity(package_version="2.24.0", policy_version="1.0"),
            project="1",
            merge_request="10",
            trace_id="0123456789abcdef",
            findings=(claim,),
            blocking=(claim,),
            suppressions=(
                SuppressionRecord(
                    rule_id="SAST.WEAK_CRYPTO",
                    location="app.py:3",
                    reason="md5 is used as a cache key, not for security",
                ),
            ),
            agent_costs=(
                AgentCost(
                    agent="security", runs=1, failures=0, tool_calls=2, tokens_allowed=800, duration_ms=90
                ),
            ),
            suggestions=(
                SuggestionRecord(rule_id="QUALITY.BARE_EXCEPT", location="app.py:4", recipe="bare-except"),
            ),
            files_considered=3,
            failure_reason="",
            recorded_at="2026-08-11T00:00:00Z",
            warnings=("the retriever was unavailable",),
        )

    def test_every_field_is_accounted_for(self):
        """A field added without a line above is a field nobody decided about.

        The whole encryption refusal rests on knowing what is in here, so
        growing the record silently is how the refusal stops being true.
        """
        from dataclasses import fields

        from code_reviewer.domain.provenance import DecisionRecord

        assert {field.name for field in fields(DecisionRecord)} == set(self.ALLOWED)

    def test_nothing_a_record_can_hold_spans_more_than_one_line(self):
        """The property that separates an identifier from a quotation.

        A rule id, a path, a producer, a fingerprint, a reason somebody typed:
        all of them fit on a line. A diff, a function body, a paragraph of
        somebody's file: none of them do. Asserted over a record built with
        every field populated, through the serialisation the sink actually
        writes, because that is the thing that would reach a store.
        """
        from code_reviewer.infrastructure.governance.json_sink import to_json

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    yield from strings(item)

        for text in strings(to_json(self._full_record())):
            assert "\n" not in text, text

    def test_the_evidence_a_finding_cites_is_identifiers(self):
        """`Provenance.evidence` says "identifiers, never the content they
        point at" and nothing enforced it. A chunk citation is an identifier; a
        chunk is not."""
        from code_reviewer.domain.provenance import Producer, ProducerKind, Provenance

        cited = Provenance(
            producer=Producer(name="retrieval", kind=ProducerKind.ANALYZER),
            rule_id="DOCS.DEAD_REFERENCE",
            location="README.md:12",
            severity="low",
            evidence=("README.md#Guide", "chunk-3"),
        )

        for item in cited.evidence:
            assert "\n" not in item
            assert len(item) <= 200

    def test_a_suppression_reason_is_the_only_free_text_and_a_person_wrote_it(self):
        """The one field somebody types. It is a reason for silencing a rule,
        not a quotation from the file — and it is in the record because a
        governance record that omits what was silenced can be gamed by
        silencing things."""
        from dataclasses import fields

        from code_reviewer.domain.provenance import SuppressionRecord

        assert {field.name for field in fields(SuppressionRecord)} == {"rule_id", "location", "reason"}


class TestFreeTextIsFlattenedWhereItEnters:
    """Self-review 30, S-02.

    Level 30 refused to encrypt the record and made its premise a test: nothing
    a record holds spans more than one line. The test built its own record, so
    it checked a record I wrote rather than the values the code can put there —
    and `failure_reason=str(refusal)` takes whatever a `ValueError` says. An
    exception message with a newline is entirely ordinary.

    A check that cannot fail for the real system is the species five
    self-reviews in a row have found. So the premise is enforced where the
    value enters, by flattening rather than by refusing: an accountability
    feature may not fail the thing it accounts for (Level 20, contract C-9),
    and a record that raised on a multi-line reason would do exactly that,
    inside the `except` that exists to write a record when something already
    went wrong.
    """

    def test_a_multiline_failure_reason_becomes_one_line(self):
        from code_reviewer.domain.provenance import DecisionRecord, RunIdentity

        record = DecisionRecord(
            verdict="warn",
            exit_code=1,
            identity=RunIdentity(package_version="1", policy_version="1"),
            completed=False,
            failure_reason="the record refused itself:\n  a blocking finding\n  names an agent",
        )

        assert "\n" not in record.failure_reason
        assert "a blocking finding names an agent" in record.failure_reason

    def test_a_multiline_warning_becomes_one_line(self):
        from code_reviewer.domain.provenance import DecisionRecord, RunIdentity

        record = DecisionRecord(
            verdict="pass",
            exit_code=0,
            identity=RunIdentity(package_version="1", policy_version="1"),
            warnings=("the retriever failed:\nconnection refused",),
        )

        assert all("\n" not in warning for warning in record.warnings)

    def test_a_multiline_suppression_reason_becomes_one_line(self):
        """The one field a person types, and a YAML block scalar is multi-line
        by construction."""
        from code_reviewer.domain.provenance import SuppressionRecord

        recorded = SuppressionRecord(
            rule_id="SAST.WEAK_CRYPTO",
            location="app.py:3",
            reason="md5 is a cache key here,\nnot a security primitive",
        )

        assert "\n" not in recorded.reason

    def test_the_refusal_a_record_actually_produces_is_covered(self):
        """The path that motivated this: `governance.py` puts `str(refusal)`
        into `failure_reason` when a record refuses itself."""
        from code_reviewer.domain.provenance import (
            DecisionRecord,
            Producer,
            ProducerKind,
            Provenance,
            RunIdentity,
        )

        opinion = Provenance(
            producer=Producer(name="agent", kind=ProducerKind.AGENT),
            rule_id="X",
            location="a.py:1",
            severity="critical",
        )
        try:
            DecisionRecord(
                verdict="fail",
                exit_code=1,
                identity=RunIdentity(package_version="1", policy_version="1"),
                blocking=(opinion,),
            )
            raise AssertionError("the record should have refused itself")
        except ValueError as refusal:
            written = DecisionRecord(
                verdict="warn",
                exit_code=1,
                identity=RunIdentity(package_version="1", policy_version="1"),
                completed=False,
                failure_reason=str(refusal),
            )

        assert "\n" not in written.failure_reason
