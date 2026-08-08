"""Step 4 — driving the analysis port over a dataset."""

from code_reviewer.application.evaluation_service import EvaluationService
from code_reviewer.application.ports import CaseFixture, EvaluationDataset, StaticAnalysis
from code_reviewer.domain.evaluation import EvaluationCase, ExpectedFinding
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity
from code_reviewer.domain.suppression import SuppressionResult, apply_suppressions


def _finding(rule_id: str, line: int) -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.HIGH,
        file_path="fixture.py",
        line_number=line,
        title=rule_id,
        description="",
        remediation="",
        rule_id=rule_id,
    )


class StubDataset(EvaluationDataset):
    def __init__(self, fixtures):
        self._fixtures = list(fixtures)

    def cases(self):
        return list(self._fixtures)


class StubAnalysis(StaticAnalysis):
    """Returns scripted findings, and records how it was called."""

    def __init__(self, by_path=None, raises=None, findings=()):
        self._by_path = by_path or {}
        self._raises = raises or {}
        self._default = list(findings)
        self.calls: list[tuple[str, str, str]] = []

    def analyze(self, file_path: str, content: str, diff: str = "") -> SuppressionResult:
        self.calls.append((file_path, content, diff))
        if file_path in self._raises:
            raise self._raises[file_path]
        produced = self._by_path.get(file_path, self._default)
        return apply_suppressions(list(produced), content)


def _fixture(name: str, *expected: ExpectedFinding, content: str = "", diff: str = "") -> CaseFixture:
    return CaseFixture(
        case=EvaluationCase(name=name, file_path=f"{name}.py", expected=tuple(expected)),
        content=content or "pass\n",
        diff=diff,
    )


def test_every_case_in_the_dataset_is_graded():
    dataset = StubDataset(
        [
            _fixture("hit", ExpectedFinding("SAST.SQL_INJECTION", 3)),
            _fixture("miss", ExpectedFinding("SAST.WEAK_CRYPTO", 9)),
        ]
    )
    analysis = StubAnalysis(by_path={"hit.py": [_finding("SAST.SQL_INJECTION", 3)]})

    report = EvaluationService(analysis).evaluate(dataset)

    assert report.case_count == 2
    assert report.overall.true_positives == 1
    assert report.overall.false_negatives == 1
    assert [result.case.name for result in report.results] == ["hit", "miss"]


def test_the_fixture_content_and_diff_both_reach_the_analyzer():
    """A diff-only rule cannot be graded if the diff is dropped on the way in."""
    dataset = StubDataset([_fixture("semantic", content="def f(): ...\n", diff="@@ -1 +1 @@\n-def f(a)")])
    analysis = StubAnalysis()

    EvaluationService(analysis).evaluate(dataset)

    assert analysis.calls == [("semantic.py", "def f(): ...\n", "@@ -1 +1 @@\n-def f(a)")]


def test_an_analyzer_that_raises_is_recorded_as_a_case_error():
    dataset = StubDataset([_fixture("boom")])
    analysis = StubAnalysis(raises={"boom.py": RecursionError("maximum recursion depth exceeded")})

    report = EvaluationService(analysis).evaluate(dataset)

    assert report.results == ()
    assert [error.name for error in report.errors] == ["boom"]
    assert "RecursionError" in report.errors[0].reason
    assert "maximum recursion depth" in report.errors[0].reason


def test_one_failing_case_does_not_abort_the_others():
    """A run reports every failure it found, not the first one it hit."""
    dataset = StubDataset(
        [
            _fixture("boom"),
            _fixture("hit", ExpectedFinding("SAST.SQL_INJECTION", 3)),
            _fixture("bang"),
        ]
    )
    analysis = StubAnalysis(
        by_path={"hit.py": [_finding("SAST.SQL_INJECTION", 3)]},
        raises={"boom.py": ValueError("one"), "bang.py": ValueError("two")},
    )

    report = EvaluationService(analysis).evaluate(dataset)

    assert [error.name for error in report.errors] == ["boom", "bang"]
    assert report.case_count == 1
    assert report.overall.true_positives == 1


def test_a_suppressed_finding_grades_as_though_the_rule_never_fired():
    """The dataset grades what a pipeline would see, and a pipeline sees the
    kept findings. Grading the suppressed half too would score the analyzers
    on output nobody is shown."""
    source = "import hashlib  # review-ignore: SAST.WEAK_CRYPTO - md5 is a cache key here\n"
    dataset = StubDataset([_fixture("suppressed", content=source)])
    analysis = StubAnalysis(findings=[_finding("SAST.WEAK_CRYPTO", 1)])

    report = EvaluationService(analysis).evaluate(dataset)

    assert report.overall.false_positives == 0
    assert report.ungraded_count == 0


def test_an_empty_dataset_reports_nothing_rather_than_raising():
    report = EvaluationService(StubAnalysis()).evaluate(StubDataset([]))

    assert report.case_count == 0
    assert report.errors == ()
