"""One line of JSON per decision.

Newline-delimited rather than one document: a service reviews many merge
requests, and one file per process would keep only the last. Appended rather
than rewritten, so a record that exists stays.

Written by opening in append mode and flushing, which is atomic enough for the
line lengths involved on every filesystem this runs on — and unlike the memory
store, a partial line here loses one record rather than the whole history.
Nothing raises: an accountability feature that can break the thing it accounts
for is a liability (contract C-9).
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from code_reviewer.application.governance import AuditSink
from code_reviewer.domain.provenance import DecisionRecord

logger = logging.getLogger(__name__)


class JsonAuditSink(AuditSink):
    """Appends each record to a newline-delimited JSON file.

    Args:
        path: Where the records go.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: DecisionRecord) -> None:
        line = json.dumps(to_json(record), sort_keys=True)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        except OSError as error:
            logger.warning("Could not write the decision record to %s: %s", self._path, error)


def to_json(record: DecisionRecord) -> dict[str, Any]:
    """The record as plain data.

    `asdict` with the enums unwrapped: a record is a tree of frozen
    dataclasses, and the only values that are not already JSON are the two
    enums inside a producer.
    """
    document = asdict(record)
    for section in ("findings", "blocking"):
        for claim in document[section]:
            claim["producer"]["kind"] = claim["producer"]["kind"].value
    document["summary"] = record.summary()
    return document
