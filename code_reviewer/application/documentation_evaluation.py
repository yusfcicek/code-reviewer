"""Grading Level 23's deterministic tier against the corpus.

Reuses the machinery Level 12 built rather than growing a second scoring
vocabulary: a case yields findings, :func:`grade` compares them against what
the case expects and forbids, and the result is the same
:class:`EvaluationReport` the analyzers are measured with. One definition of
precision in this repository is worth more than two that agree today.

Only `DOCS` is graded. `DRIFT`'s answer comes from a model, and a corpus that
pinned a model's answers would be measuring the recording. That tier is bounded
by attribution — nothing it produces can block — and by the caps in
`drift_service.py`, which is a different kind of guarantee and is stated as one.
"""

from collections.abc import Sequence

from code_reviewer.application.documentation_service import DocumentationService
from code_reviewer.domain.evaluation import CaseError, EvaluationReport, grade


def evaluate_documentation(fixtures: Sequence) -> EvaluationReport:
    """Runs the rules over every case and scores what they reported.

    A case that raises is recorded as an error rather than silently scoring
    zero: "the rules crashed" and "the rules found nothing" are different
    facts, and a harness that conflates them reports a clean sheet for a broken
    build (the reasoning Level 12 wrote into `EvaluationReport.errors`).
    """
    results = []
    errors = []

    for fixture in fixtures:
        try:
            outcome = DocumentationService(index=fixture.index, documents=fixture.documents).review(
                list(fixture.changes), dict(fixture.sources)
            )
        except Exception as error:  # pragma: no cover - defensive; the service does not raise
            errors.append(CaseError(name=fixture.case.name, reason=type(error).__name__))
            continue
        results.append(grade(fixture.case, outcome.findings))

    return EvaluationReport(results=tuple(results), errors=tuple(errors))
