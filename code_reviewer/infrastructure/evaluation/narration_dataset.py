"""Reads recorded reviews and the facts they were written about.

A sibling of :mod:`dataset`, not an extension of it. Level 12's cases are
``(fixture, expected findings)``; these are ``(fixture, recorded prose)``, and a
loader serving both would have every case reading the other's optional keys —
the same argument Level 14 made against reusing Level 13's index, reaching the
same conclusion (decision D-5).

Strict for the reason that one is: a corpus is ground truth, so a key nobody
reads is a claim nobody checks. One rule is new. A recorded review is model
output produced from real files, and this project spent four levels keeping
credential-shaped text out of its memory, its trace, its record and its
comment. A case whose review carries one **refuses to load**, and the refusal
does not quote it (contract C-7).
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.narration import NarrationCase
from code_reviewer.domain.severity import Severity
from code_reviewer.errors import ConfigurationError
from code_reviewer.infrastructure.security.redaction import SecretRedactor
from code_reviewer.infrastructure.tools.workspace import OutsideWorkspaceError, Workspace

#: Where recorded reviews live under the dataset root.
NARRATION_DIRECTORY = "narration"

_CASE_KEYS = frozenset({"name", "file", "review", "findings", "prompt_fingerprint", "expect_failures"})
_FINDING_KEYS = frozenset({"rule", "line", "severity", "title", "category"})


class NarrationDatasetError(ConfigurationError):
    """A corpus that cannot be read, or a case that cannot be believed.

    A :class:`~code_reviewer.errors.ConfigurationError`, so the command maps it
    to "the measurement could not be taken" rather than "the measurement came
    out low" — the two exit codes Level 12 separated for the same reason
    (contract C-9).
    """


class NarrationCorpus:
    """Every ``narration/*.yaml`` under a root, with its fixture read from disk.

    Args:
        root: Directory holding ``narration/`` and the fixtures the cases name.
        redactor: Injected by a test. Built from the shipped patterns
            otherwise — the values this process holds are irrelevant here,
            because what matters is the shape of what somebody committed.
    """

    def __init__(self, root: str | Path, redactor: SecretRedactor | None = None):
        self._root = Path(root)
        self._redactor = redactor or SecretRedactor()

    def cases(self) -> list[NarrationCase]:
        """Loads every case, sorted by file name.

        Sorted so two runs' reports diff cleanly: a report whose row order
        depends on the filesystem is a report nobody can compare.
        """
        directory = self._root / NARRATION_DIRECTORY
        if not directory.is_dir():
            raise NarrationDatasetError(
                f"No recorded reviews at '{directory}': the directory does not exist."
            )

        paths = sorted(directory.glob("*.yaml"))
        if not paths:
            raise NarrationDatasetError(
                f"No cases in '{directory}'. An empty corpus is a broken harness rather than a "
                "score of zero, and the two exit differently."
            )

        workspace = Workspace(self._root)
        cases = [self._load(path, workspace) for path in paths]

        seen: set[str] = set()
        for case in cases:
            if case.name in seen:
                raise NarrationDatasetError(
                    f"Two cases are both called '{case.name}'. Case names key the report, "
                    "so they have to be unique."
                )
            seen.add(case.name)

        return cases

    # -- internals ----------------------------------------------------------

    def _load(self, path: Path, workspace: Workspace) -> NarrationCase:
        raw = self._parse(path)

        unknown = set(raw) - _CASE_KEYS
        if unknown:
            raise NarrationDatasetError(
                f"{path.name}: unknown key(s) {sorted(unknown)}. A case may declare {sorted(_CASE_KEYS)}."
            )

        name = str(raw.get("name") or path.stem)
        file_path = raw.get("file")
        if not file_path:
            raise NarrationDatasetError(
                f"{path.name}: a case must name the file its review was written about, under 'file'."
            )

        review = str(raw.get("review") or "")
        self._refuse_secrets(review, name)

        content = self._read(str(file_path), name, workspace)
        try:
            return NarrationCase(
                name=name,
                file_path=str(file_path),
                line_count=len(content.splitlines()),
                review=review,
                findings=tuple(
                    self._finding(entry, name, str(file_path))
                    for entry in _sequence(raw.get("findings"), name)
                ),
                prompt_fingerprint=str(raw.get("prompt_fingerprint") or ""),
                expected_failures=tuple(str(check) for check in _sequence(raw.get("expect_failures"), name)),
            )
        except ValueError as refusal:
            raise NarrationDatasetError(f"{path.name}: {refusal}") from refusal

    def _refuse_secrets(self, review: str, name: str) -> None:
        """Refuses a review carrying credential-shaped text.

        The message says where, never what: an error that quotes the secret it
        found has published it to the CI log, which is the one place this whole
        rule exists to keep it out of.
        """
        result = self._redactor.redact_with_report(review)
        if result.count:
            raise NarrationDatasetError(
                f"{name}: the recorded review contains {result.count} secret-shaped span(s). "
                "A corpus is committed and read widely; re-record it with the value removed."
            )

    @staticmethod
    def _parse(path: Path) -> Mapping[str, Any]:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise NarrationDatasetError(f"{path.name}: could not be read — {error}") from error

        if not isinstance(loaded, Mapping):
            raise NarrationDatasetError(
                f"{path.name}: a case file must be a mapping, not {type(loaded).__name__}."
            )
        return loaded

    @staticmethod
    def _finding(entry: Any, case_name: str, file_path: str) -> Finding:
        if not isinstance(entry, Mapping):
            raise NarrationDatasetError(f"{case_name}: each entry under 'findings' must be a mapping.")

        unknown = set(entry) - _FINDING_KEYS
        if unknown:
            raise NarrationDatasetError(f"{case_name}: unknown key(s) in a finding: {sorted(unknown)}.")

        rule = entry.get("rule")
        line = entry.get("line")
        severity = entry.get("severity")
        if not rule:
            raise NarrationDatasetError(f"{case_name}: a finding must name a 'rule'.")
        if not isinstance(line, int) or isinstance(line, bool):
            raise NarrationDatasetError(f"{case_name}: the finding for '{rule}' needs a 'line'.")
        if not severity:
            raise NarrationDatasetError(
                f"{case_name}: the finding for '{rule}' needs a 'severity'. The prose's severity "
                "claims are checked against these, so an unstated one grades nothing."
            )

        try:
            parsed = Severity(str(severity).lower())
        except ValueError as error:
            raise NarrationDatasetError(
                f"{case_name}: '{severity}' is not a severity this project reports."
            ) from error

        return Finding(
            category=_category(entry.get("category"), case_name),
            severity=parsed,
            file_path=file_path,
            line_number=line,
            title=str(entry.get("title") or rule),
            description="",
            remediation="",
            rule_id=str(rule),
        )

    @staticmethod
    def _read(relative: str, case_name: str, workspace: Workspace) -> str:
        try:
            return workspace.read(workspace.root / relative)
        except OutsideWorkspaceError as error:
            raise NarrationDatasetError(
                f"{case_name}: '{relative}' is outside the corpus. A case file arrives in a merge "
                "request, so its paths are read through the same confinement everything else is."
            ) from error
        except Exception as error:
            raise NarrationDatasetError(f"{case_name}: could not read '{relative}' — {error}") from error


def _sequence(value: Any, case_name: str) -> Sequence[Any]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise NarrationDatasetError(f"{case_name}: 'findings' and 'expect_failures' must be lists.")
    return value


def _category(value: Any, case_name: str) -> FindingCategory:
    if not value:
        return FindingCategory.SECURITY
    try:
        return FindingCategory(str(value).lower())
    except ValueError as error:
        raise NarrationDatasetError(f"{case_name}: '{value}' is not a finding category.") from error
