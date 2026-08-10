"""Reading the retrieval corpus off disk.

The sibling of the other three loaders, and the same bargain: a case that
cannot be read completely is refused rather than graded, because a corpus that
silently drops a case reports a better number than the retriever earned.

A case carries its own documents inline. That is deliberate — the question
"given this change, does this section come back" is only fair if a reader can
see the whole haystack, and a corpus whose documents live elsewhere is a corpus
nobody audits.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from code_reviewer.application.retrieval_recall import RecallCase
from code_reviewer.errors import ConfigurationError


class RetrievalDatasetError(ConfigurationError):
    """A case that could not be read."""


#: Where the cases live under a dataset root, matching the other corpora.
SUBDIRECTORY = "retrieval"


class RetrievalCorpus:
    """Every ``retrieval/*.yaml`` under a root, in a stable order."""

    def __init__(self, root: str | Path):
        given = Path(root)
        nested = given / SUBDIRECTORY
        self._root = nested if nested.is_dir() else given

    def cases(self) -> list[RecallCase]:
        if not self._root.is_dir():
            raise RetrievalDatasetError(f"No retrieval corpus at '{self._root}'")
        return [self._load(path) for path in sorted(self._root.glob("*.yaml"))]

    def _load(self, path: Path) -> RecallCase:
        raw = self._parse(path)
        name = str(raw.get("name") or path.stem)

        expect = raw.get("expect")
        if not isinstance(expect, Mapping) or not expect.get("path") or not expect.get("heading"):
            raise RetrievalDatasetError(f"Case '{name}' does not say which section should be found")

        documents = raw.get("documents")
        if not isinstance(documents, Mapping) or not documents:
            raise RetrievalDatasetError(f"Case '{name}' carries no documents to search")

        return RecallCase(
            name=name,
            diff=str(raw.get("diff") or ""),
            path=str(expect["path"]),
            heading=str(expect["heading"]),
            documents=tuple((str(key), str(value)) for key, value in documents.items()),
            because=str(raw.get("because") or ""),
        )

    @staticmethod
    def _parse(path: Path) -> Mapping[str, Any]:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise RetrievalDatasetError(
                f"Could not read case '{path.name}': {type(error).__name__}"
            ) from error
        if not isinstance(loaded, Mapping):
            raise RetrievalDatasetError(f"Case '{path.name}' is not a mapping")
        return loaded
