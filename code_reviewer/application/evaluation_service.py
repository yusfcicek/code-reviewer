"""Running the analysis suite over an annotated dataset and scoring it.

The use case is deliberately thin: the grading rules are in the domain and the
cases come from a port, so this module is the part that can only be written
once — the loop that turns "what a dataset says" and "what the analyzers do"
into one report.

It drives :class:`~code_reviewer.application.ports.StaticAnalysis` and nothing
else, which is what makes the harness model-free, network-free and fast enough
to run on every push (decision D-6). When Level 15 introduces specialist agents
they arrive behind a port too, and the same service grades them.
"""

import logging

from code_reviewer.domain.evaluation import CaseError, CaseResult, EvaluationReport, grade

from .ports import EvaluationDataset, StaticAnalysis

logger = logging.getLogger(__name__)


class EvaluationService:
    """Grades every case a dataset offers."""

    def __init__(self, analysis: StaticAnalysis):
        self._analysis = analysis

    def evaluate(self, dataset: EvaluationDataset) -> EvaluationReport:
        """Scores the dataset, recording rather than raising on a failed case.

        A case whose analysis raises is an error, not a zero: "the analyzer
        crashed" and "the analyzer found nothing" are different facts and only
        one of them is a measurement (contract C-9). The run continues so that
        one report names every broken case rather than the first — a fix-one-
        rerun loop over a dataset is the thing nobody does twice.
        """
        results: list[CaseResult] = []
        errors: list[CaseError] = []

        for fixture in dataset.cases():
            case = fixture.case
            try:
                analysed = self._analysis.analyze(case.file_path, fixture.content, fixture.diff)
            except Exception as error:
                logger.error("Evaluation case %s could not be analysed: %s", case.name, error)
                errors.append(CaseError(name=case.name, reason=f"{type(error).__name__}: {error}"))
                continue

            # `analysed.findings` is the kept half. Grading the suppressed half
            # too would score the analyzers on output no pipeline is shown.
            results.append(grade(case, analysed.findings))

        return EvaluationReport(results=tuple(results), errors=tuple(errors))
