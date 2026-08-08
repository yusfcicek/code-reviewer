"""Step 5 — the two shapes a run is reported in."""

import json

from code_reviewer.application.evaluation_report import evaluation_summary, render_evaluation_report
from code_reviewer.domain.evaluation import (
    CaseError,
    EvaluationCase,
    EvaluationReport,
    EvaluationThreshold,
    ExpectedFinding,
    grade,
)
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity


def _finding(rule_id: str, line: int, severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path="fixture.py",
        line_number=line,
        title=rule_id,
        description="",
        remediation="",
        rule_id=rule_id,
    )


def _report() -> EvaluationReport:
    hit = grade(
        EvaluationCase(
            name="sql-injection",
            file_path="sql.py",
            expected=(ExpectedFinding("SAST.SQL_INJECTION", 4),),
            scope=("SAST.*",),
        ),
        [
            _finding("SAST.SQL_INJECTION", 4),
            _finding("SAST.HARDCODED_SECRET", 12),
            _finding("QUALITY.GOD_CLASS", 30),
        ],
    )
    miss = grade(
        EvaluationCase(
            name="weak-crypto",
            file_path="crypto.py",
            expected=(ExpectedFinding("SAST.WEAK_CRYPTO", 7),),
        ),
        [],
    )
    return EvaluationReport(results=(hit, miss))


def test_the_markdown_carries_the_overall_scores():
    text = render_evaluation_report(_report())

    assert "| precision | 0.50 |" in text
    assert "| recall | 0.50 |" in text
    assert "| f1 | 0.50 |" in text


def test_the_markdown_carries_one_row_per_rule():
    text = render_evaluation_report(_report())

    assert "SAST.SQL_INJECTION" in text
    assert "SAST.WEAK_CRYPTO" in text


def test_the_markdown_names_every_case_and_its_score():
    text = render_evaluation_report(_report())

    assert "sql-injection" in text
    assert "weak-crypto" in text


def test_ungraded_findings_are_stated_with_their_rules():
    text = render_evaluation_report(_report())

    assert "1 ungraded" in text
    assert "QUALITY.GOD_CLASS" in text


def test_a_run_with_nothing_ungraded_says_so_rather_than_omitting_the_section():
    """An absent section reads as an oversight; a zero reads as a fact."""
    report = EvaluationReport(
        results=(grade(EvaluationCase(name="clean", file_path="c.py"), []),),
    )

    assert "0 ungraded" in render_evaluation_report(report)


def test_shortfalls_appear_when_a_threshold_is_supplied():
    text = render_evaluation_report(_report(), EvaluationThreshold(min_f1=0.9))

    assert "f1 0.50 is below the floor of 0.90" in text


def test_a_case_error_is_reported_above_the_scores():
    report = EvaluationReport(errors=(CaseError(name="boom", reason="ValueError: x"),))

    text = render_evaluation_report(report)

    assert "boom" in text
    assert "ValueError" in text


def test_the_summary_round_trips_through_json_and_agrees_with_the_markdown():
    report = _report()
    threshold = EvaluationThreshold(min_precision=0.9, min_recall=0.9, min_f1=0.9)

    summary = json.loads(json.dumps(evaluation_summary(report, threshold)))

    assert summary["cases"] == 2
    assert summary["overall"] == {
        "true_positives": 1,
        "false_positives": 1,
        "false_negatives": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }
    assert summary["by_rule"]["SAST.WEAK_CRYPTO"]["false_negatives"] == 1
    assert summary["ungraded"] == {"count": 1, "rule_ids": ["QUALITY.GOD_CLASS"]}
    assert len(summary["shortfalls"]) == 3
    assert summary["errors"] == []


def test_the_summary_without_a_threshold_reports_no_shortfalls():
    summary = evaluation_summary(_report())

    assert summary["shortfalls"] == []
