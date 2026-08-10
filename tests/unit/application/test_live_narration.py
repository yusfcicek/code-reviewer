"""Step 6 — grading what the configured model produces now.

Level 21 refused to call a model in CI, and that refusal still stands for the
default run: a test suite whose result depends on a remote service fails for
reasons unrelated to the code. What it left open is that **a prompt edit ships
unmeasured** — Level 20 records which prompt produced a review, and Level 21
grades a review no current prompt produced.

`--live` closes that, opt-in, with the recording untouched.
"""

import pytest

from code_reviewer.application.live_narration import LiveNarration, grade_live
from code_reviewer.domain.narration import NarrationCase

CLEAN = """## 🔒 Security Analysis
- **SAST Scan Result**: PASS
- **Vulnerabilities Found**: None

## 🔍 Semantic Change Analysis
- **Change Type**: REFACTOR

## 🔗 Impact Analysis
- **Dependencies Checked**: `fixtures/subject.py`

## 📊 Code Quality
- **SOLID Compliance**: 90/100

## ⚡ Performance Analysis
- **Complexity Issues**: None
"""

BROKEN = "I reject this merge request.\n"


class _Reviewer:
    """Produces what it was told to, and remembers what it was asked."""

    def __init__(self, text=CLEAN, error=None):
        self._text = text
        self._error = error
        self.briefs = []

    def review_diff(self, brief):
        self.briefs.append(brief)
        if self._error is not None:
            raise self._error
        return self._text


def _case(name="one", review=BROKEN, expected_failures=()):
    return NarrationCase(
        name=name,
        file_path="fixtures/subject.py",
        line_count=20,
        review=review,
        findings=(),
        expected_failures=tuple(expected_failures),
    )


def _source(case):
    return "def f():\n    return 1\n"


class TestItGradesTheFreshOutput:
    def test_a_good_live_review_passes_even_when_the_recording_is_terrible(self):
        """AC-10 — the recording is not consulted. The stored review here would
        fail a check; the live one does not."""
        outcome = grade_live([_case(review=BROKEN)], _Reviewer(CLEAN), _source)

        assert outcome.report.score_interval.point == 1.0

    def test_a_bad_live_review_fails_even_when_the_recording_is_perfect(self):
        outcome = grade_live([_case(review=CLEAN)], _Reviewer(BROKEN), _source)

        assert outcome.report.score_interval.point < 1.0

    def test_the_reviewer_is_given_the_file_the_case_names(self):
        reviewer = _Reviewer()

        grade_live([_case()], reviewer, _source)

        assert reviewer.briefs[0].file_path == "fixtures/subject.py"

    def test_the_reviewer_is_given_the_source_and_the_findings(self):
        reviewer = _Reviewer()

        grade_live([_case()], reviewer, _source)

        assert reviewer.briefs[0].full_content == _source(None)
        assert reviewer.briefs[0].findings == ()

    def test_every_case_is_asked_about(self):
        reviewer = _Reviewer()

        grade_live([_case("a"), _case("b")], reviewer, _source)

        assert len(reviewer.briefs) == 2

    def test_a_declared_failure_still_counts_as_agreement(self):
        """A case built to break a check is graded against its declaration, the
        same way the recorded corpus is."""
        # BROKEN claims a verdict *and* has no sections; a case that declared
        # only the first would be an inaccurate case rather than a failing one.
        outcome = grade_live(
            [_case(expected_failures=["the_prose_claims_no_verdict", "required_sections_are_present"])],
            _Reviewer(BROKEN),
            _source,
        )

        assert outcome.report.score_interval.point == 1.0


class TestWhenTheModelFails:
    def test_a_failing_case_is_named_rather_than_scored(self):
        """A measurement with a hole in it must say where the hole is."""
        outcome = grade_live([_case("a")], _Reviewer(error=RuntimeError("timeout")), _source)

        assert outcome.unreachable == ("a",)

    def test_a_failing_case_is_not_graded(self):
        outcome = grade_live([_case("a")], _Reviewer(error=RuntimeError("timeout")), _source)

        assert outcome.report.case_count == 0

    def test_one_failure_does_not_cost_the_others(self):
        class _Flaky(_Reviewer):
            def review_diff(self, brief):
                self.briefs.append(brief)
                if len(self.briefs) == 1:
                    raise RuntimeError("timeout")
                return CLEAN

        outcome = grade_live([_case("a"), _case("b")], _Flaky(), _source)

        assert outcome.unreachable == ("a",)
        assert outcome.report.case_count == 1

    def test_a_source_that_cannot_be_read_is_named_too(self):
        def _missing(case):
            raise OSError("no such file")

        outcome = grade_live([_case("a")], _Reviewer(), _missing)

        assert outcome.unreachable == ("a",)

    def test_every_case_failing_is_reported_rather_than_scored_zero(self):
        """Nothing measured is not a score of nought, and a floor applied to it
        would be a floor applied to nothing."""
        outcome = grade_live([_case("a"), _case("b")], _Reviewer(error=RuntimeError("x")), _source)

        assert outcome.report.case_count == 0
        assert len(outcome.unreachable) == 2


class TestTheDefaultRunNeverCallsAModel:
    def test_live_grading_is_not_reachable_from_the_recorded_path(self):
        """AC-12, asserted by parsing rather than by a sentence: the module
        that grades recordings must not import the one that calls a model."""
        import ast
        from pathlib import Path

        tree = ast.parse(Path("code_reviewer/application/narration_evaluation.py").read_text())
        imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

        assert not any("live" in name for name in imported)

    def test_grade_live_needs_a_reviewer_and_will_not_invent_one(self):
        with pytest.raises(TypeError):
            grade_live([_case()])  # type: ignore[call-arg]


def test_the_outcome_carries_both_halves():
    outcome = LiveNarration(report=None, unreachable=("a",))

    assert outcome.unreachable == ("a",)
