"""Steps 4–5 — assembling the record, and writing it."""

import json
from datetime import UTC, datetime

from code_reviewer.application.governance import (
    PRODUCERS,
    AuditSink,
    DecisionRecorder,
    producer_for,
    provenance_of,
)
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.gate import GateEvaluation, ReviewGateResult
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.provenance import AgentCost, ProducerKind, RunIdentity
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import SuppressedFinding, SuppressionDirective
from code_reviewer.infrastructure.governance.json_sink import JsonAuditSink, to_json

SECRET = "AKIAIOSFODNN7EXAMPLE"
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

IDENTITY = RunIdentity(
    package_version="2.13.0",
    policy_version="1.0",
    model="qwen3-8b",
    prompt_fingerprint="abc123def456",
    ruleset_version="2.13.0",
    evaluation_baseline="precision >= 0.95",
)


def _finding(rule_id="SAST.SQL_INJECTION", severity=Severity.CRITICAL) -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path="storage/repository.py",
        line_number=11,
        title="SQL Injection",
        description=f"A query built from {SECRET}",
        remediation=f"Do not interpolate {SECRET}",
        rule_id=rule_id,
        cwe_id="CWE-89",
        evidence=f"query = '...' + {SECRET}",
    )


class RecordingSink(AuditSink):
    def __init__(self, error=None):
        self.error = error
        self.written = []

    def write(self, record):
        if self.error is not None:
            raise self.error
        self.written.append(record)


def _blocking_outcome() -> ReviewOutcome:
    outcome = ReviewOutcome()
    outcome.record(
        "storage/repository.py",
        GateEvaluation(
            result=ReviewGateResult.FAIL,
            exit_code=1,
            reasons=[],
            scores={},
            blocking_issues=["critical finding"],
        ),
    )
    return outcome


def _recorder(sink=None) -> tuple[DecisionRecorder, RecordingSink]:
    sink = sink or RecordingSink()
    return DecisionRecorder(sink, IDENTITY, clock=lambda: NOW), sink


def _is_critical(finding: Finding) -> bool:
    return finding.severity is Severity.CRITICAL


# -- attribution -------------------------------------------------------------


def test_every_analyzer_namespace_is_attributed_to_an_analyzer():
    for namespace in ("SAST", "QUALITY", "PERFORMANCE", "SEMANTIC", "DEPENDENCY"):
        producer = producer_for(f"{namespace}.RULE", "2.13.0")

        assert producer.kind is ProducerKind.ANALYZER, namespace
        assert producer.is_deterministic


def test_a_sandbox_refusal_is_attributed_to_a_tool():
    """A refused read is a fact about the request rather than an opinion about
    the code, which is why it has been allowed to block since Level 8."""
    producer = producer_for("SANDBOX.VIOLATION", "2.13.0")

    assert producer.kind is ProducerKind.TOOL
    assert producer.is_deterministic


def test_an_unregistered_namespace_is_treated_as_an_opinion():
    """Fail-closed: an unattributable claim cannot block until somebody says
    what produced it."""
    producer = producer_for("MYSTERY.RULE", "2.13.0")

    assert not producer.is_deterministic


def test_every_namespace_the_suite_emits_is_registered():
    """So the fail-closed default never fires in practice, and a new analyzer
    is a red test rather than a silent misattribution."""
    from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite

    source = open("evaluation/fixtures/sql_injection.py", encoding="utf-8").read()
    result = StaticAnalysisSuite().analyze("sql_injection.py", source, "")

    for finding in result.findings:
        namespace = finding.rule_id.split(".", 1)[0]
        assert namespace in PRODUCERS, f"{namespace} is unattributed"


def test_provenance_carries_identifiers_and_not_content():
    claim = provenance_of(_finding(), "2.13.0")

    assert claim.rule_id == "SAST.SQL_INJECTION"
    assert claim.location == "storage/repository.py:11"
    assert claim.evidence == ("CWE-89",)
    assert SECRET not in repr(claim)


# -- the record --------------------------------------------------------------


def test_a_blocking_review_records_what_blocked_it():
    recorder, sink = _recorder()

    record = recorder.record(
        _blocking_outcome(),
        [_finding()],
        _is_critical,
        project="17",
        merge_request="42",
        trace_id="17-42",
        exit_code=1,
    )

    assert record.verdict == "fail"
    assert record.deciders == ("analyzer:SASTAnalyzer@2.13.0",)
    assert sink.written == [record]


def test_a_passing_review_records_no_blocking_claims():
    recorder, _ = _recorder()

    record = recorder.record(ReviewOutcome(), [_finding(severity=Severity.LOW)], _is_critical)

    assert record.verdict == "pass"
    assert record.blocking == ()
    assert len(record.findings) == 1


def test_suppressions_reach_the_record_with_their_reasons():
    outcome = ReviewOutcome()
    outcome.record_suppressions(
        "cache/keys.py",
        [
            SuppressedFinding(
                finding=_finding("SAST.WEAK_CRYPTO"),
                directive=SuppressionDirective(
                    rule_id="SAST.WEAK_CRYPTO", reason="md5 is a cache key here", line=4
                ),
            )
        ],
    )
    recorder, _ = _recorder()

    record = recorder.record(outcome, [], _is_critical)

    assert record.suppressions[0].rule_id == "SAST.WEAK_CRYPTO"
    assert record.suppressions[0].location == "cache/keys.py:4"
    assert "cache key" in record.suppressions[0].reason


def test_per_agent_cost_reaches_the_record():
    recorder, _ = _recorder()

    record = recorder.record(
        ReviewOutcome(),
        [],
        _is_critical,
        agent_costs=[AgentCost(agent="security", runs=1, tool_calls=3, tokens_allowed=4000)],
    )

    assert record.agent_costs[0].agent == "security"


def test_the_record_carries_the_runs_identity():
    recorder, _ = _recorder()

    record = recorder.record(ReviewOutcome(), [], _is_critical)

    assert record.identity is IDENTITY
    assert record.recorded_at == NOW.isoformat()


# -- what must never be in it ------------------------------------------------


def test_nothing_from_the_code_under_review_reaches_the_record():
    """An audit file is read by more people than a merge request, and a diff
    may contain a secret. The finding here carries the same credential-shaped
    string in its description, its remediation and its evidence."""
    recorder, sink = _recorder()

    recorder.record(_blocking_outcome(), [_finding()], _is_critical, exit_code=1)

    written = json.dumps(to_json(sink.written[0]), sort_keys=True)
    assert SECRET not in written
    assert "query = " not in written


# -- failure -----------------------------------------------------------------


def test_a_record_that_refuses_itself_is_written_as_incomplete():
    """The invariant doing its job. A missing file is indistinguishable from a
    review nobody ran, so the honest response is a record saying so."""
    recorder, sink = _recorder()

    record = recorder.record(_blocking_outcome(), [_finding("MYSTERY.RULE")], _is_critical, exit_code=1)

    assert not record.completed
    assert "may not rest on a model's opinion" in record.failure_reason
    assert sink.written == [record]


def test_a_sink_that_raises_is_logged_and_the_review_continues(caplog):
    recorder, _ = _recorder(RecordingSink(error=OSError("read-only file system")))

    with caplog.at_level("WARNING", logger="code_reviewer.application.governance"):
        record = recorder.record(ReviewOutcome(), [], _is_critical)

    assert record is not None
    assert "could not be written" in caplog.text


# -- the sink ----------------------------------------------------------------


def test_the_sink_appends_one_line_per_record(tmp_path):
    """A service reviews many merge requests, and one file per process would
    keep only the last."""
    sink = JsonAuditSink(tmp_path / "audit" / "decisions.jsonl")
    recorder = DecisionRecorder(sink, IDENTITY, clock=lambda: NOW)

    recorder.record(ReviewOutcome(), [], _is_critical, merge_request="1")
    recorder.record(ReviewOutcome(), [], _is_critical, merge_request="2")

    lines = sink.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["merge_request"] for line in lines] == ["1", "2"]


def test_a_written_record_round_trips_through_json(tmp_path):
    sink = JsonAuditSink(tmp_path / "decisions.jsonl")
    recorder = DecisionRecorder(sink, IDENTITY, clock=lambda: NOW)

    recorder.record(_blocking_outcome(), [_finding()], _is_critical, exit_code=1)

    document = json.loads(sink.path.read_text(encoding="utf-8").strip())
    assert document["verdict"] == "fail"
    assert document["identity"]["prompt_fingerprint"] == "abc123def456"
    assert document["blocking"][0]["producer"]["kind"] == "analyzer"
    assert document["summary"].startswith("blocked by")


def test_an_unwritable_destination_is_a_warning(tmp_path, caplog):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")
    sink = JsonAuditSink(blocked / "decisions.jsonl")

    with caplog.at_level("WARNING", logger="code_reviewer.infrastructure.governance.json_sink"):
        sink.write(_recorder()[0].record(ReviewOutcome(), [], _is_critical))

    assert "Could not write the decision record" in caplog.text
