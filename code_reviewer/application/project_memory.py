"""What this project's reviews remember, and what this review adds to it.

The use case around :class:`~code_reviewer.domain.recollection.Recollection`.
It loads once per run, answers "what is known about this file" from what was
known *before* the run started, collects what this run observed, and writes the
consolidated result at the end.

Recall reads the pre-run memory on purpose. A finding reported for the first
time this morning is not a recurring finding, and a memory that counted the
sighting it is currently describing would say it was.

Nothing here raises. A store that cannot be read is an empty memory; a store
that cannot be written is a log line. Every review before this level ran with
no history at all, which is precisely what a failed load produces
(contract C-8).
"""

import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import date

from code_reviewer.domain.finding import Finding
from code_reviewer.domain.recollection import (
    Recollection,
    RecollectionKind,
    consolidate,
    forget,
    recall_for,
    retain,
)

from .ports import MemoryStore

logger = logging.getLogger(__name__)

#: Most recollections kept in one store. Past it the least salient are
#: forgotten first — a bound is what stops the file becoming a log.
DEFAULT_CAPACITY = 2_000

#: Most recollections handed to the reviewer for one file.
DEFAULT_RECALL_LIMIT = 8


class ProjectMemory:
    """One repository's review history, for the length of one run.

    Args:
        store: Where the history is kept.
        clock: Returns today's date. Injected so a test is not at the mercy of
            the calendar.
        capacity: Ceiling on the stored history.
        recall_limit: Ceiling on what one file's prompt is told.
    """

    def __init__(
        self,
        store: MemoryStore,
        clock: Callable[[], date] | None = None,
        capacity: int = DEFAULT_CAPACITY,
        recall_limit: int = DEFAULT_RECALL_LIMIT,
    ):
        self._store = store
        self._clock = clock or date.today
        self._capacity = capacity
        self._recall_limit = recall_limit

        self._known: list[Recollection] | None = None
        self._observed: list[Recollection] = []

    # -- reading ------------------------------------------------------------

    @property
    def known(self) -> list[Recollection]:
        """What was remembered before this run, loaded at most once."""
        if self._known is None:
            try:
                self._known = list(self._store.load())
            except Exception as error:
                logger.warning("Could not read the project memory; reviewing without it: %s", error)
                self._known = []
        return self._known

    def recall(self, file_path: str) -> list[Recollection]:
        """What is worth telling a reviewer about ``file_path``."""
        return recall_for(file_path, self.known, self._clock(), limit=self._recall_limit)

    def recurrence_of(self, finding: Finding) -> Recollection | None:
        """What is known about this rule in this file, or ``None`` if it is new.

        Looked up against the pre-run memory, so a finding is "recurring" only
        when a *previous* review reported it.
        """
        if not finding.rule_id:
            return None
        wanted = (RecollectionKind.FINDING, finding.file_path, finding.rule_id)
        return next((item for item in self.known if item.identity == wanted), None)

    # -- writing ------------------------------------------------------------

    def observe_findings(self, findings: Iterable[Finding]) -> None:
        """Records that these rules fired, where they fired.

        A finding with no rule id contributes nothing: identity is what makes a
        memory a memory rather than a list, and there is nothing to key on.
        """
        today = self._clock()
        self._observed.extend(
            Recollection(
                kind=RecollectionKind.FINDING,
                file_path=finding.file_path,
                rule_id=finding.rule_id,
                severity=finding.severity,
                first_seen=today,
                last_seen=today,
            )
            for finding in findings
            if finding.rule_id and finding.file_path
        )

    def observe_suppressions(self, file_path: str, suppressed: Iterable) -> None:
        """Records that somebody decided a rule should be silent here."""
        today = self._clock()
        for item in suppressed:
            directive = item.directive
            if not directive.rule_id:
                continue
            self._observed.append(
                Recollection(
                    kind=RecollectionKind.SUPPRESSION,
                    file_path=file_path,
                    rule_id=directive.rule_id,
                    severity=item.finding.severity,
                    first_seen=today,
                    last_seen=today,
                    # The only free text stored, and it is written by the
                    # repository's maintainers in a source comment rather than
                    # by the change under review (decision D-3).
                    reason=directive.reason,
                )
            )

    def persist(self) -> None:
        """Consolidates this run's observations into the store.

        Consolidate, then forget what has decayed below the floor, then cap.
        In that order: forgetting before consolidating would drop a fact this
        run has just seen again, which is the one moment it is least stale.
        """
        if not self._observed and self._known is None:
            # Nothing was read and nothing was seen. Rewriting the file to say
            # so would only churn its timestamp.
            return

        today = self._clock()
        merged = consolidate(self.known, self._observed)
        kept = retain(forget(merged, today), today, self._capacity)

        try:
            self._store.save(kept)
        except Exception as error:
            logger.warning("Could not write the project memory; this run is not remembered: %s", error)

    @property
    def observed(self) -> Sequence[Recollection]:
        """What this run has seen so far. Exposed for reporting and tests."""
        return tuple(self._observed)
