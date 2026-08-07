"""Unit tests for metrics collection and export.

`export_prometheus` serialised `self._metrics[-1]`. One record is kept per
file, so a merge request touching twelve files exported the twelfth and
discarded eleven (F-16). Several exported fields were declared, exported and
never populated, so a dashboard built on them showed a flat line and was
believed (F-17).
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from code_reviewer.infrastructure.metrics.collector import MetricsCollector, ReviewMetrics


def _metric(path="src/app.py", decision="full", gate="pass", **kwargs):
    defaults = {
        "project_id": "7",
        "mr_id": "12",
        "file_path": path,
        "lines_analyzed": 40,
        "triage_decisions": {decision: 1},
        "gate_result": gate,
        "quality_score": 90,
        "duration_ms": 120,
    }
    defaults.update(kwargs)
    return ReviewMetrics(**defaults)


def _collector(*metrics):
    collector = MetricsCollector()
    for metric in metrics:
        collector.record(metric)
    return collector


class TestAggregate(unittest.TestCase):
    def test_files_are_counted_across_the_review(self):
        aggregate = _collector(_metric("a.py"), _metric("b.py"), _metric("c.py")).aggregate()

        self.assertEqual(aggregate.files_analyzed, 3)

    def test_lines_are_summed(self):
        aggregate = _collector(_metric(lines_analyzed=10), _metric(lines_analyzed=32)).aggregate()

        self.assertEqual(aggregate.lines_analyzed, 42)

    def test_triage_decisions_are_counted_across_files(self):
        aggregate = _collector(
            _metric(decision="full"), _metric(decision="full"), _metric(decision="auto")
        ).aggregate()

        self.assertEqual(aggregate.triage_decisions["full"], 2)
        self.assertEqual(aggregate.triage_decisions["auto"], 1)

    def test_findings_are_counted_by_severity(self):
        aggregate = _collector(
            _metric(findings_by_severity={"critical": 1, "low": 2}),
            _metric(findings_by_severity={"critical": 1}),
        ).aggregate()

        self.assertEqual(aggregate.findings_by_severity["critical"], 2)
        self.assertEqual(aggregate.findings_by_severity["low"], 2)

    def test_the_worst_gate_result_wins(self):
        aggregate = _collector(_metric(gate="pass"), _metric(gate="fail"), _metric(gate="warn")).aggregate()

        self.assertEqual(aggregate.gate_result, "fail")

    def test_a_warning_beats_a_pass(self):
        aggregate = _collector(_metric(gate="pass"), _metric(gate="warn")).aggregate()

        self.assertEqual(aggregate.gate_result, "warn")

    def test_the_lowest_quality_score_is_reported(self):
        aggregate = _collector(_metric(quality_score=90), _metric(quality_score=40)).aggregate()

        self.assertEqual(aggregate.quality_score, 40)

    def test_unknown_quality_scores_are_ignored(self):
        aggregate = _collector(_metric(quality_score=None), _metric(quality_score=70)).aggregate()

        self.assertEqual(aggregate.quality_score, 70)

    def test_durations_are_summed_and_the_slowest_is_kept(self):
        aggregate = _collector(_metric(duration_ms=100), _metric(duration_ms=400)).aggregate()

        self.assertEqual(aggregate.duration_ms, 500)
        self.assertEqual(aggregate.slowest_file_ms, 400)

    def test_an_empty_collector_aggregates_to_zero(self):
        aggregate = MetricsCollector().aggregate()

        self.assertEqual(aggregate.files_analyzed, 0)
        self.assertEqual(aggregate.gate_result, "pass")


class TestPrometheusExport(unittest.TestCase):
    def test_every_series_has_help_and_type(self):
        text = _collector(_metric()).export_prometheus()

        series = {
            line.split("{")[0].split(" ")[0]
            for line in text.splitlines()
            if line and not line.startswith("#")
        }
        for name in series:
            with self.subTest(series=name):
                self.assertIn(f"# HELP {name}", text)
                self.assertIn(f"# TYPE {name}", text)

    def test_each_value_line_is_name_labels_value(self):
        text = _collector(_metric(findings_by_severity={"high": 2})).export_prometheus()

        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            with self.subTest(line=line):
                name_and_labels, _, value = line.rpartition(" ")
                self.assertTrue(name_and_labels)
                float(value)  # raises if the value is not numeric

    def test_totals_reflect_every_file_not_only_the_last(self):
        """Regression for F-16."""
        text = _collector(
            _metric("a.py", lines_analyzed=10),
            _metric("b.py", lines_analyzed=10),
            _metric("c.py", lines_analyzed=10),
        ).export_prometheus()

        self.assertIn("code_review_files_analyzed", text)
        self.assertIn("} 3", text)
        self.assertIn("} 30", text)

    def test_finding_counts_are_exported_per_severity(self):
        """Regression for F-17."""
        text = _collector(_metric(findings_by_severity={"critical": 2})).export_prometheus()

        self.assertIn("code_review_findings{", text)
        self.assertIn('severity="critical"', text)

    def test_labels_carry_project_and_merge_request(self):
        text = _collector(_metric()).export_prometheus()

        self.assertIn('project_id="7"', text)
        self.assertIn('mr_id="12"', text)

    def test_gate_result_is_exported_as_a_number(self):
        passing = _collector(_metric(gate="pass")).export_prometheus()
        failing = _collector(_metric(gate="fail")).export_prometheus()

        self.assertIn("code_review_gate_passed{", passing)
        self.assertIn("} 1", passing)
        self.assertIn("} 0", failing)

    def test_an_empty_collector_exports_nothing(self):
        self.assertEqual(MetricsCollector().export_prometheus(), "")


class TestFileExport(unittest.TestCase):
    def test_metrics_are_written_to_the_given_path(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "metrics.txt"

            _collector(_metric()).export_gitlab_metrics(str(target))

            self.assertIn("code_review_files_analyzed", target.read_text(encoding="utf-8"))

    def test_json_export_contains_every_file(self):
        import json

        with TemporaryDirectory() as directory:
            target = Path(directory) / "metrics.json"

            _collector(_metric("a.py"), _metric("b.py")).export_json(str(target))

            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual([entry["file_path"] for entry in payload], ["a.py", "b.py"])

    def test_an_unwritable_path_does_not_raise(self):
        _collector(_metric()).export_gitlab_metrics("/nonexistent-directory/metrics.txt")


if __name__ == "__main__":
    unittest.main()
