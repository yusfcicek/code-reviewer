"""Tier A of Level 23 — the documentation defects a change proves.

Two directions meet here, and they are the same question asked from either end.
The code changed, so every document that named what it removed is stale by
proof. The documents changed, so what they now claim is checked against the
tree while their author is still holding the merge request open.

Everything this service emits is `Severity.LOW`, and that is a decision rather
than a shrug. The rules have never been measured against a dataset, and this
repository's rule since Level 12 is that a floor is earned by the level that
measured it. Emitting nothing above `LOW` is the cheapest way to make "no
documentation finding blocks a merge" true — cheaper than a gate exception,
and much harder to remove by accident.

The degradation is the other half. An index that did not build silences every
rule that needs one, and saying so in the outcome is what keeps the silence
from reading as a clean bill of health (self-review 12–20, S-02).
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from code_reviewer.application.ports import FileChange
from code_reviewer.domain.documentation import (
    ChangeScope,
    DocDefect,
    SymbolIndex,
    claims_in,
    docstring_defects,
    documentation_defects,
    scope_from_diff,
)
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity

logger = logging.getLogger(__name__)

#: The namespace Level 20's attribution table registers as deterministic.
NAMESPACE = "DOCS"

#: Documents this tier reads.
DOCUMENT_SUFFIXES = frozenset({".md", ".markdown"})

#: Sources whose docstrings it reads.
SOURCE_SUFFIXES = frozenset({".py"})

#: What each rule is called in a report, and what to do about it. Written once
#: here so the wording is the same in every finding — and so that the wording
#: is reviewable in one place, which matters for text this level will print
#: about somebody's writing.
_WORDING: Mapping[str, tuple[str, str]] = {
    "DEAD_REFERENCE": (
        "Documentation names a symbol this change removed",
        "Update or delete the reference. It resolved before this change and does not now.",
    ),
    "SIGNATURE_MISMATCH": (
        "Documentation states a signature the code does not have",
        "Bring the documented parameter names into line with the definition.",
    ),
    "UNKNOWN_OPTION": (
        "Documentation names an option or variable this change removed",
        "Update or delete the reference; nothing in the code reads it now.",
    ),
    "BROKEN_EXAMPLE": (
        "A fenced Python example does not parse",
        "Fix the block, or mark the fence with the language it is actually in.",
    ),
    "DOCSTRING_DRIFT": (
        "A docstring describes something the function does not do",
        "Bring the docstring's sections into line with the signature and the body.",
    ),
}


@dataclass(frozen=True)
class DocumentationSummary:
    """Both tiers of Level 23, as the renderer and the recorder need them.

    They travel together and are never merged. One is a set of facts about the
    repository; the other is a model's selection. Presenting them as one list
    would hand the whole namespace the weaker tier's credibility, which is how
    a reader learns to skim past a section.
    """

    #: Tier A — proved by the change.
    resolved: Sequence[Finding] = ()
    #: Tier B — retrieved and judged, verified by nothing.
    candidates: Sequence[Finding] = ()
    #: Why a tier could not run, one line per tier that could not.
    degraded: tuple[str, ...] = ()
    #: Candidates the cap discarded before the model saw them.
    dropped: int = 0

    @property
    def findings(self) -> list[Finding]:
        """Everything, for the recorder — which keys on namespace anyway."""
        return [*self.resolved, *self.candidates]

    @property
    def is_empty(self) -> bool:
        return not (self.resolved or self.candidates or self.degraded)


@dataclass(frozen=True)
class DocumentationOutcome:
    """What the tier found, and whether it was able to look."""

    findings: list[Finding] = field(default_factory=list)
    #: Why the tier could not do its work, empty when it could. Present in the
    #: outcome rather than only in a log, because a silence nobody can see is
    #: indistinguishable from a clean result.
    degraded: str = ""


class DocumentationService:
    """Checks a change against the repository's prose, and the prose against it."""

    def __init__(self, index: SymbolIndex, documents: Sequence[tuple[str, str | None]]):
        self._index = index
        self._documents = list(documents)

    def review(self, changes: Sequence[FileChange], sources: Mapping[str, str]) -> DocumentationOutcome:
        """Every defect this change proves, as findings.

        ``sources`` holds the *current* content of the files under review, keyed
        by path; a file absent from it is simply not checked for docstring
        drift. Never raises: a documentation check that fails a review would be
        the observability defect this project has refused five times.
        """
        if self._index.is_empty:
            logger.info("Documentation review skipped: the symbol index did not build")
            return DocumentationOutcome(
                degraded="the symbol index did not build, so nothing could be resolved"
            )

        scope = self._scope_of(changes)
        edited = {change.path for change in changes}

        findings = self._document_findings(scope, edited)
        findings.extend(self._docstring_findings(changes, sources))
        return DocumentationOutcome(findings=findings)

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _scope_of(changes: Sequence[FileChange]) -> ChangeScope:
        scope = ChangeScope()
        for change in changes:
            if _suffix(change.path) in SOURCE_SUFFIXES:
                scope = scope.merged_with(scope_from_diff(change.diff))
        return scope

    def _document_findings(self, scope: ChangeScope, edited: set[str]) -> list[Finding]:
        findings: list[Finding] = []
        for path, text in self._documents:
            if not text:
                # A document that could not be read costs that document and
                # nothing else, the same answer `corpus.py` gives.
                continue
            defects = documentation_defects(
                claims_in(text, named=scope.names), self._index, scope.for_document(path in edited)
            )
            findings.extend(_finding(path, defect) for defect in defects)
        return findings

    @staticmethod
    def _docstring_findings(changes: Sequence[FileChange], sources: Mapping[str, str]) -> list[Finding]:
        findings: list[Finding] = []
        for change in changes:
            if _suffix(change.path) not in SOURCE_SUFFIXES:
                continue
            source = sources.get(change.path)
            if not source:
                continue
            findings.extend(_finding(change.path, defect) for defect in docstring_defects(source))
        return findings


def _suffix(path: str) -> str:
    return Path(path).suffix.lower()


def _finding(path: str, defect: DocDefect) -> Finding:
    """One defect as a finding — identifiers only, on purpose.

    The subject, the rule, the location and the heading. Never the sentence:
    this is the first level whose findings are about English somebody wrote,
    and quoting it back inside a machine's report is both worse manners and a
    new way to leak content into an artefact that five levels have kept free
    of it.
    """
    title, remediation = _WORDING.get(defect.rule, ("Documentation drift", "Check the reference."))
    where = f" under '{defect.heading}'" if defect.heading else ""
    return Finding(
        category=FindingCategory.DOCUMENTATION,
        severity=Severity.LOW,
        file_path=path,
        line_number=defect.line,
        title=title,
        description=f"`{defect.subject}`{where}: {defect.detail}" if defect.subject else defect.detail,
        remediation=remediation,
        rule_id=f"{NAMESPACE}.{defect.rule}",
    )
