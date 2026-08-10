"""Reading the documentation corpus off disk.

The sibling of `dataset.py` and `narration_dataset.py`, and the same bargain:
the case says what the inputs are and what must and must not be reported, and
the loader refuses anything it cannot read rather than grading a case it half
understood. A corpus that silently drops a case reports a better score than the
rules deserve.

Unlike the analyzer corpus, a case carries its inputs inline rather than
naming a fixture. A documentation case is a symbol index, a diff and a few
lines of Markdown — small enough to read in one screen, and much easier to
review as one file than as four.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from code_reviewer.application.ports import FileChange
from code_reviewer.domain.documentation import SymbolIndex
from code_reviewer.domain.evaluation import EvaluationCase, ExpectedFinding, ForbiddenFinding
from code_reviewer.errors import ConfigurationError


class DocumentationDatasetError(ConfigurationError):
    """A case that could not be read. Never carries the file's content."""


@dataclass(frozen=True)
class DocumentationFixture:
    """One graded case: what to run the rules over, and what to expect."""

    case: EvaluationCase
    index: SymbolIndex
    changes: tuple[FileChange, ...] = ()
    documents: tuple[tuple[str, str], ...] = ()
    sources: Mapping[str, str] = field(default_factory=dict)


#: Where the cases live under a dataset root, matching `narration/`.
SUBDIRECTORY = "documentation"


class DocumentationCorpus:
    """Every ``documentation/*.yaml`` under a root, in a stable order.

    Args:
        root: The dataset directory. Either the root holding
            ``documentation/`` — which is what ``--dataset`` names for every
            other corpus — or that subdirectory itself. Accepting both keeps
            one flag meaning one thing across three harnesses.
    """

    def __init__(self, root: str | Path):
        given = Path(root)
        nested = given / SUBDIRECTORY
        self._root = nested if nested.is_dir() else given

    def cases(self) -> list[DocumentationFixture]:
        if not self._root.is_dir():
            raise DocumentationDatasetError(f"No documentation corpus at '{self._root}'")
        return [self._load(path) for path in sorted(self._root.glob("*.yaml"))]

    # -- internals ----------------------------------------------------------

    def _load(self, path: Path) -> DocumentationFixture:
        raw = self._parse(path)
        name = str(raw.get("name") or path.stem)

        return DocumentationFixture(
            case=EvaluationCase(
                name=name,
                file_path=name,
                expected=tuple(_expectation(entry, name) for entry in _listed(raw, "expected")),
                forbidden=tuple(_prohibition(entry, name) for entry in _listed(raw, "forbidden")),
            ),
            index=_index(raw.get("index") or {}, name),
            changes=tuple(_change(entry, name) for entry in _listed(raw, "changes")),
            documents=tuple((str(key), str(value)) for key, value in (raw.get("documents") or {}).items()),
            sources={str(key): str(value) for key, value in (raw.get("sources") or {}).items()},
        )

    @staticmethod
    def _parse(path: Path) -> Mapping[str, Any]:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise DocumentationDatasetError(
                f"Could not read case '{path.name}': {type(error).__name__}"
            ) from error
        if not isinstance(loaded, Mapping):
            raise DocumentationDatasetError(f"Case '{path.name}' is not a mapping")
        return loaded


def _listed(raw: Mapping[str, Any], key: str) -> Sequence[Any]:
    value = raw.get(key) or []
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise DocumentationDatasetError(f"'{key}' must be a list")
    return value


def _index(raw: Mapping[str, Any], case: str) -> SymbolIndex:
    if not isinstance(raw, Mapping):
        raise DocumentationDatasetError(f"Case '{case}' has an index that is not a mapping")
    signatures = raw.get("signatures") or {}
    return SymbolIndex(
        names=frozenset(str(name) for name in raw.get("names") or []),
        signatures={str(key): tuple(str(part) for part in value) for key, value in signatures.items()},
        options=frozenset(str(flag) for flag in raw.get("options") or []),
        environment=frozenset(str(name) for name in raw.get("environment") or []),
    )


def _change(entry: Any, case: str) -> FileChange:
    if not isinstance(entry, Mapping) or "path" not in entry:
        raise DocumentationDatasetError(f"Case '{case}' has a change with no path")
    return FileChange(path=str(entry["path"]), diff=str(entry.get("diff") or ""))


def _expectation(entry: Any, case: str) -> ExpectedFinding:
    if not isinstance(entry, Mapping) or "rule" not in entry:
        raise DocumentationDatasetError(f"Case '{case}' has an expectation with no rule")
    return ExpectedFinding(rule_id=str(entry["rule"]), line_number=int(entry.get("line") or 0))


def _prohibition(entry: Any, case: str) -> ForbiddenFinding:
    if not isinstance(entry, Mapping) or "rule" not in entry:
        raise DocumentationDatasetError(f"Case '{case}' forbids something with no rule")
    return ForbiddenFinding(rule_id=str(entry["rule"]), line_number=int(entry.get("line") or 0))
