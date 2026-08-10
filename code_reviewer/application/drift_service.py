"""Tier B of Level 23 — the sections a change might have made stale.

The deterministic tier can only see a document that names something. The common
case names nothing: a paragraph explaining how suppression works, three levels
after suppression changed. No parser reaches that, and the user asking for this
level asked for exactly it — *any* relationship, scanned deeply.

So the documents go into the retrieval corpus Levels 13 and 16 built, the
changed code is the query, and what comes back is a list of **candidates**. A
candidate is not a finding. It becomes one only if a model, asked one narrow
question about it, says the section is stale — and even then it is a `DRIFT`
finding, which the attribution table registers as an `AGENT` and which
therefore cannot appear in a blocking verdict.

Three bounds keep this from being a way to spend an afternoon's tokens on
prose: a per-file retrieval limit, a global cap on how many candidates reach
the model, and the rule that a document the change already edited is never a
candidate. What the cap dropped is returned, not logged — a truncation nobody
can see reads as coverage.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from code_reviewer.application.ports import CodeRetriever, DriftJudge, FileChange
from code_reviewer.domain.drift import DriftCandidate, DriftVerdict
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity

logger = logging.getLogger(__name__)

#: The namespace Level 20's attribution table registers as non-deterministic.
NAMESPACE = "DRIFT"

#: Sections retrieved per changed file.
DEFAULT_PER_FILE = 3

#: Sections that may reach the model in one run, across every changed file.
#: A merge request touching forty files would otherwise ask a hundred and
#: twenty questions about prose.
DEFAULT_CAP = 8

#: How relevant a section must be to be worth a model call.
#:
#: Reciprocal rank fusion's scores are small and unbounded below — a chunk
#: fused from two rankings at position twenty scores around 1/80 — so this is a
#: floor on *being ranked at all* rather than a similarity threshold anybody
#: should read as a percentage. Stated as a constant with its reasoning because
#: a parameter with a default nobody chose is a number nobody can defend.
DEFAULT_RELEVANCE_FLOOR = 0.005


@dataclass(frozen=True)
class DriftOutcome:
    """What the tier produced, and everything it could not do."""

    findings: list[Finding] = field(default_factory=list)
    #: Why the tier did not run, empty when it did.
    degraded: str = ""
    #: Candidates the cap discarded. Stated so a reader knows the list is
    #: partial; a silent truncation reads as "we looked at everything".
    dropped: int = 0
    #: Candidates the relevance floor discarded, for the same reason.
    below_floor: int = 0
    #: Whether the floor could be applied at all. ``False`` when the retriever
    #: has no notion of a score — the old behaviour, now visible instead of
    #: implied (Level 27, AC-5).
    floor_applied: bool = True


class DriftService:
    """Retrieves the sections a change may have invalidated, and asks about them."""

    def __init__(
        self,
        retriever: CodeRetriever,
        judge: DriftJudge,
        per_file: int = DEFAULT_PER_FILE,
        cap: int = DEFAULT_CAP,
        floor: float = DEFAULT_RELEVANCE_FLOOR,
    ):
        self._retriever = retriever
        self._judge = judge
        self._per_file = per_file
        self._cap = cap
        self._floor = floor

    def review(
        self, changes: Sequence[FileChange], documents: Mapping[str, str] | None = None
    ) -> DriftOutcome:
        """Candidates that survived a model's answer, as findings.

        ``documents`` names the documents the change already edited; those are
        never candidates. Updating the README in the same merge request is the
        behaviour this level wants, and reporting it would train people out of
        it (C-6).

        Never raises. A retriever or a model that fails costs this tier and
        nothing else — observability may not fail the review it observes.
        """
        edited = set(documents or {})
        try:
            candidates, dropped, below, applied = self._candidates(changes, edited)
        except Exception as error:
            logger.warning("Drift candidates unavailable: %s", error)
            return DriftOutcome(degraded=f"retrieval was unavailable: {type(error).__name__}")

        findings: list[Finding] = []
        for candidate in candidates:
            verdict = self._ask(candidate)
            if verdict.is_reportable:
                findings.append(_finding(candidate))

        return DriftOutcome(findings=findings, dropped=dropped, below_floor=below, floor_applied=applied)

    # -- internals ----------------------------------------------------------

    def _candidates(
        self, changes: Sequence[FileChange], edited: set[str]
    ) -> tuple[list[DriftCandidate], int, int, bool]:
        found: list[DriftCandidate] = []
        below = 0
        applied = True

        for change in changes:
            if _is_document(change.path) or not change.diff:
                continue
            for result in self._retriever.scored(change.diff, limit=self._per_file):
                if not result.is_scored:
                    # The retriever has no notion of a score, so the floor
                    # cannot be applied. Reported rather than silently skipped:
                    # a floor that quietly passes everything is how Level 23
                    # lost a whole tier for a whole level (Level 27, AC-5).
                    applied = False
                elif result.score < self._floor:
                    below += 1
                    continue

                chunk = result.chunk
                if not _is_document(chunk.path) or chunk.path in edited:
                    continue
                found.append(
                    DriftCandidate(
                        path=chunk.path,
                        line=chunk.start_line,
                        heading=chunk.name,
                        text=chunk.text,
                        source_path=change.path,
                        diff=change.diff,
                    )
                )

        unique = _deduplicated(found)
        if len(unique) <= self._cap:
            return unique, 0, below, applied
        return unique[: self._cap], len(unique) - self._cap, below, applied

    def _ask(self, candidate: DriftCandidate) -> DriftVerdict:
        """One candidate, one question. A model that fails answers `UNSURE`."""
        try:
            return self._judge.still_describes(candidate)
        except Exception as error:
            logger.warning("Drift judge failed for %s: %s", candidate.path, error)
            return DriftVerdict.UNSURE


def _deduplicated(candidates: Sequence[DriftCandidate]) -> list[DriftCandidate]:
    """One section, one question, however many files pointed at it."""
    seen: set[tuple[str, int]] = set()
    unique: list[DriftCandidate] = []
    for candidate in candidates:
        key = (candidate.path, candidate.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _is_document(path: str) -> bool:
    return Path(path).suffix.lower() in {".md", ".markdown"}


def _finding(candidate: DriftCandidate) -> Finding:
    """A candidate as a finding — a place to look, never a claim of error."""
    where = f"'{candidate.heading}'" if candidate.heading else "this section"
    return Finding(
        category=FindingCategory.DOCUMENTATION,
        severity=Severity.INFO,
        file_path=candidate.path,
        line_number=candidate.line,
        title="A documentation section may no longer describe this change",
        description=(
            f"{where} was retrieved as related to the change in `{candidate.source_path}` "
            "and the model judged it out of date. Unverified: nothing here was resolved against the code."
        ),
        remediation="Read the section against the change and update it, or leave it if it still holds.",
        rule_id=f"{NAMESPACE}.POSSIBLE_STALE_SECTION",
    )
