"""Measuring the half of the drift tier that is measurable.

Level 27. Level 23 said the retrieved tier could not be measured because its
answer comes from a model, and a corpus that pinned a model's answers would
measure the recording. That is true of the *judgement* and it was taken to be
true of the whole tier.

The tier has two halves. Whether the section a reader says is related was
**retrieved** is deterministic: run the retriever, look for the section, record
the rank. No model, no recording, no author's opinion about correctness — only
whether the thing reached the model at all.

That is also exactly the half that failed. The self-review of Level 23 found the
tier returning nothing, undetected for a level, because the retrieval never
produced a candidate. This measurement fails when that happens.

What is still not measured, and is stated rather than implied: whether the model
was right about a candidate it saw. That needs a human on every case, and a
corpus of "correct" answers would measure its author.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from code_reviewer.application.ports import CodeRetriever
from code_reviewer.domain.confidence import Interval, wilson

#: What a rank of nought means: the section was not in the results at all.
NOT_RETRIEVED = 0


@dataclass(frozen=True)
class RecallCase:
    """One change, and the document section a reader says relates to it."""

    name: str
    diff: str
    #: Where the related section is: path and heading.
    path: str
    heading: str
    #: The documents to search. Carried by the case so a reader can see the
    #: whole question in one screen, the way the documentation corpus does.
    documents: tuple[tuple[str, str], ...] = ()
    #: Why a human says these relate. Never read by the code; read by whoever
    #: has to decide whether the case is fair.
    because: str = ""


@dataclass(frozen=True)
class RecallResult:
    """Whether one case's section was retrieved, and where in the list."""

    case: str
    #: 1-based position, or :data:`NOT_RETRIEVED`.
    rank: int = NOT_RETRIEVED
    #: What came back instead, for a case that missed.
    retrieved: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return self.rank != NOT_RETRIEVED


@dataclass(frozen=True)
class RecallReport:
    """What the retriever found, over how many cases, at what limit."""

    results: tuple[RecallResult, ...] = ()
    limit: int = 0
    #: Cases that could not be run at all — a corpus that names a document it
    #: does not carry. Distinct from a case that missed.
    errors: tuple[str, ...] = field(default=())

    @property
    def found(self) -> int:
        return sum(1 for result in self.results if result.found)

    @property
    def missed(self) -> tuple[str, ...]:
        return tuple(result.case for result in self.results if not result.found)

    @property
    def interval(self) -> Interval:
        """Recall, and the rates still consistent with it.

        Over **cases**, which are independent by construction: each carries its
        own documents and its own change (Level 25's rule, applied here).
        """
        return wilson(self.found, len(self.results))

    @property
    def first_rank_share(self) -> float:
        """How often the related section came back *first*.

        Reported because the tier's per-file limit is three: "in the top twenty"
        and "first" are different facts about a retriever whose results are then
        capped.
        """
        if not self.results:
            return 0.0
        return sum(1 for result in self.results if result.rank == 1) / len(self.results)


def measure_recall(cases: Sequence[RecallCase], build_retriever, limit: int) -> RecallReport:
    """Runs each case's change against its own documents and records the rank.

    ``build_retriever`` takes a case's documents and returns something indexed
    over them. Injected so this layer neither chunks nor indexes — it asks a
    question and counts the answers.
    """
    results: list[RecallResult] = []
    errors: list[str] = []

    for case in cases:
        if not any(path == case.path for path, _ in case.documents):
            # A corpus that names a document it does not carry is a broken
            # case, not a missed one. Level 12's rule about errors and scores.
            errors.append(case.name)
            continue

        retriever: CodeRetriever = build_retriever(case.documents)
        chunks = retriever.related(case.diff, limit=limit)
        results.append(
            RecallResult(
                case=case.name,
                rank=_rank_of(chunks, case),
                retrieved=tuple(f"{chunk.path}#{chunk.name}" for chunk in chunks),
            )
        )

    return RecallReport(results=tuple(results), limit=limit, errors=tuple(errors))


def _rank_of(chunks, case: RecallCase) -> int:
    """Where the case's section appeared, or :data:`NOT_RETRIEVED`."""
    for position, chunk in enumerate(chunks, start=1):
        if chunk.path == case.path and chunk.name == case.heading:
            return position
    return NOT_RETRIEVED


def render_recall_report(report: RecallReport, floor: float) -> str:
    """The measurement as markdown: the number, the ranks, and what missed."""
    interval = report.interval
    lines = [
        "# Drift retrieval recall",
        "",
        f"{len(report.results)} case(s), asking for the top {report.limit}.",
        "",
        f"**Recall**: {interval} (floor {floor:.2f} on the lower bound) — "
        f"{'met' if interval.lower >= floor else 'BELOW THE FLOOR'}",
        "",
        f"_{interval.method}, {interval.confidence:.0%}, over cases. This measures whether the "
        "related section reached the model, and nothing about whether the model was right "
        "about it — that needs a human on every case._",
        "",
        f"**First place**: {report.first_rank_share:.0%} of cases returned the related section "
        "at rank 1. The tier's per-file limit is three, so rank is not a detail.",
        "",
    ]

    if report.results:
        lines += ["| case | rank |", "|---|---:|"]
        lines += [
            f"| `{result.case}` | {result.rank if result.found else '—'} |" for result in report.results
        ]
        lines.append("")

    if report.missed:
        lines += [
            f"**{len(report.missed)} case(s) missed**, named rather than averaged:",
            "",
            *[f"- `{case}`" for case in report.missed],
            "",
        ]

    if report.errors:
        lines += [
            f"**{len(report.errors)} case(s) could not be run** — a case naming a document it "
            "does not carry is broken, not missed:",
            "",
            *[f"- `{case}`" for case in report.errors],
            "",
        ]

    return "\n".join(lines)
