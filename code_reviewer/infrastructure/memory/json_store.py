"""One JSON file per repository, written atomically.

A review agent that needs a datastore provisioned before it can run is a review
agent nobody rolls out. So the shipped :class:`MemoryStore` is a file in the
checkout — and because it is a file, everything about it is about not losing
what was there before.

**Atomic.** Written to a temporary file beside the destination and moved into
place, so a run killed mid-write leaves the previous memory intact rather than
a truncated one.

**No lock.** Two reviews of the same repository racing will have one overwrite
the other's increment. Losing one count from a decaying score is not worth a
lock file that can be left behind by a killed runner (decision D-6).

**Tolerant of its own file.** A memory that cannot be parsed is reported and
treated as empty. It is not deleted: whoever wants to look at it still can, and
a tool that silently removes state it does not understand is a tool nobody
trusts with state.
"""

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from code_reviewer.application.ports import MemoryStore
from code_reviewer.domain.recollection import Recollection, RecollectionKind
from code_reviewer.domain.severity import Severity

logger = logging.getLogger(__name__)

#: Where the memory lives, relative to the workspace root.
DEFAULT_MEMORY_FILENAME = ".review-memory.json"

#: The format this adapter writes. A file claiming a version it does not
#: recognise loads as empty rather than half-read: guessing at a newer schema
#: is how a downgrade quietly corrupts a history.
SCHEMA_VERSION = 1


class JsonMemoryStore(MemoryStore):
    """The project's review history, as one file.

    Args:
        path: Where the file lives.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[Recollection]:
        if not self._path.is_file():
            return []

        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning("Project memory at %s could not be read: %s", self._path, error)
            return []

        if not isinstance(document, dict):
            logger.warning("Project memory at %s is not an object; ignoring it", self._path)
            return []

        version = document.get("version")
        if version != SCHEMA_VERSION:
            logger.warning(
                "Project memory at %s is version %r, not %d; starting from an empty memory",
                self._path,
                version,
                SCHEMA_VERSION,
            )
            return []

        entries = document.get("recollections")
        if not isinstance(entries, list):
            logger.warning("Project memory at %s has no recollections list; ignoring it", self._path)
            return []

        return [item for item in (_read_entry(entry) for entry in entries) if item is not None]

    def save(self, recollections: list[Recollection]) -> None:
        document = {
            "version": SCHEMA_VERSION,
            "recollections": [_write_entry(item) for item in recollections],
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(self._path.name + ".tmp")

        try:
            temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temporary, self._path)
        finally:
            # A failed rename must not leave a half-written sibling behind for
            # the next run to wonder about.
            temporary.unlink(missing_ok=True)


# -- serialisation ----------------------------------------------------------


def _write_entry(recollection: Recollection) -> dict[str, Any]:
    return {
        "kind": recollection.kind.value,
        "file_path": recollection.file_path,
        "rule_id": recollection.rule_id,
        "severity": recollection.severity.value,
        "first_seen": recollection.first_seen.isoformat(),
        "last_seen": recollection.last_seen.isoformat(),
        "occurrences": recollection.occurrences,
        "reason": recollection.reason,
    }


def _read_entry(entry: Any) -> Recollection | None:
    """One recollection, or ``None`` for anything unreadable.

    A malformed entry is skipped rather than failing the load. The file is
    written by this program, so a bad entry means it was edited by hand or
    written by a different version — and losing one line of history is a much
    smaller loss than losing all of it.
    """
    if not isinstance(entry, dict):
        return None

    try:
        return Recollection(
            kind=RecollectionKind(entry["kind"]),
            file_path=str(entry["file_path"]),
            rule_id=str(entry["rule_id"]),
            severity=Severity(entry["severity"]),
            first_seen=date.fromisoformat(entry["first_seen"]),
            last_seen=date.fromisoformat(entry["last_seen"]),
            occurrences=int(entry["occurrences"]),
            reason=str(entry.get("reason", "")),
        )
    except (KeyError, TypeError, ValueError) as error:
        logger.warning("Skipping an unreadable recollection: %s", error)
        return None
