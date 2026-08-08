"""Reads annotated evaluation cases from a directory of YAML files.

A case written as a Python test function can only be run by the test runner and
can only be extended by someone editing this repository. Cases on disk beside
their fixtures can be generated, contributed, and eventually exported from a
real review — which is the difference between a fixture set and a dataset
(decision D-2).

The loader is strict about everything. A dataset is ground truth, so a key
nobody reads is a claim nobody checks: an unknown key, a missing line, an
unparseable severity and a fixture that is not there all refuse to load rather
than degrading into a case that grades less than it appears to. That is the
same rule the policy loader follows after Level 9, applied to the one file
whose whole purpose is to be believed.

A case file is also untrusted input in the ordinary sense — it arrives in a
merge request — so fixture paths are resolved through :class:`Workspace`, which
is where this project already states what confinement means.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from code_reviewer.application.ports import CaseFixture, EvaluationDataset
from code_reviewer.domain.evaluation import EVERYTHING, EvaluationCase, ExpectedFinding, ForbiddenFinding
from code_reviewer.domain.severity import Severity
from code_reviewer.errors import ConfigurationError
from code_reviewer.infrastructure.tools.workspace import OutsideWorkspaceError, Workspace

#: Where cases live under the dataset root.
CASES_DIRECTORY = "cases"

_CASE_KEYS = frozenset({"name", "file", "diff", "scope", "line_tolerance", "expect", "expect_absent"})
_EXPECT_KEYS = frozenset({"rule", "line", "severity"})
_ABSENT_KEYS = frozenset({"rule", "line"})


class DatasetError(ConfigurationError):
    """A dataset that cannot be read, or a case that cannot be believed.

    A :class:`~code_reviewer.errors.ConfigurationError` because that is what it
    is: nothing has been measured, retrying will not help, and the exit code
    the command maps it to means "the measurement could not be taken" rather
    than "the measurement came out low" (contract C-8).
    """


class FileSystemDataset(EvaluationDataset):
    """Every ``cases/*.yaml`` under a root, with its fixture read from disk.

    Args:
        root: Directory holding ``cases/`` and the fixtures they name.
    """

    def __init__(self, root: str | Path):
        self._root = Path(root)

    def cases(self) -> list[CaseFixture]:
        """Loads every case, sorted by file name.

        Sorted so that two runs' reports diff cleanly: a report whose row order
        depends on the filesystem is a report nobody can compare.
        """
        directory = self._root / CASES_DIRECTORY
        if not directory.is_dir():
            raise DatasetError(f"No evaluation cases at '{directory}': the directory does not exist.")

        workspace = Workspace(self._root)
        fixtures = [self._load(path, workspace) for path in sorted(directory.glob("*.yaml"))]

        seen: dict[str, str] = {}
        for fixture in fixtures:
            name = fixture.case.name
            if name in seen:
                raise DatasetError(
                    f"Two cases are both called '{name}' ({seen[name]} and {fixture.case.file_path}). "
                    "Case names key the report, so they have to be unique."
                )
            seen[name] = fixture.case.file_path

        return fixtures

    # -- internals ----------------------------------------------------------

    def _load(self, path: Path, workspace: Workspace) -> CaseFixture:
        raw = self._parse(path)
        unknown = set(raw) - _CASE_KEYS
        if unknown:
            raise DatasetError(
                f"{path.name}: unknown key(s) {sorted(unknown)}. A case may declare {sorted(_CASE_KEYS)}."
            )

        name = str(raw.get("name") or path.stem)
        file_path = raw.get("file")
        if not file_path:
            raise DatasetError(f"{path.name}: a case must name the fixture it annotates, under 'file'.")

        case = EvaluationCase(
            name=name,
            file_path=str(file_path),
            expected=tuple(self._expectation(item, name) for item in _sequence(raw, "expect", name)),
            forbidden=tuple(self._prohibition(item, name) for item in _sequence(raw, "expect_absent", name)),
            scope=_scope(raw.get("scope"), name),
            line_tolerance=_tolerance(raw.get("line_tolerance"), name),
        )

        return CaseFixture(
            case=case,
            content=self._read(str(file_path), name, workspace),
            diff=self._read(str(raw["diff"]), name, workspace) if raw.get("diff") else "",
        )

    @staticmethod
    def _parse(path: Path) -> Mapping[str, Any]:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise DatasetError(f"{path.name}: could not be read — {error}") from error

        if not isinstance(loaded, Mapping):
            raise DatasetError(f"{path.name}: a case file must be a mapping, not {type(loaded).__name__}.")
        return loaded

    @staticmethod
    def _expectation(entry: Any, case_name: str) -> ExpectedFinding:
        mapping = _mapping(entry, case_name, "expect")
        _reject_unknown(mapping, _EXPECT_KEYS, case_name, "expect")

        rule = mapping.get("rule")
        line = mapping.get("line")
        if not rule:
            raise DatasetError(f"{case_name}: an expectation must name a 'rule'.")
        if not isinstance(line, int) or isinstance(line, bool):
            raise DatasetError(
                f"{case_name}: expectation for '{rule}' needs a 'line', "
                "because a rule that fires somewhere else has not done its job."
            )

        return ExpectedFinding(
            rule_id=str(rule),
            line_number=line,
            severity=_severity(mapping.get("severity"), case_name, str(rule)),
        )

    @staticmethod
    def _prohibition(entry: Any, case_name: str) -> ForbiddenFinding:
        mapping = _mapping(entry, case_name, "expect_absent")
        _reject_unknown(mapping, _ABSENT_KEYS, case_name, "expect_absent")

        rule = mapping.get("rule")
        if not rule:
            raise DatasetError(f"{case_name}: a prohibition must name a 'rule'.")

        line = mapping.get("line", 0)
        if not isinstance(line, int) or isinstance(line, bool):
            raise DatasetError(f"{case_name}: prohibition for '{rule}' has a non-numeric 'line'.")

        return ForbiddenFinding(rule_id=str(rule), line_number=line)

    def _read(self, relative: str, case_name: str, workspace: Workspace) -> str:
        try:
            resolved = workspace.resolve(relative)
        except OutsideWorkspaceError as error:
            raise DatasetError(f"{case_name}: '{relative}' is outside the dataset — {error}") from error

        try:
            return resolved.read_text(encoding="utf-8")
        except OSError as error:
            raise DatasetError(f"{case_name}: fixture '{relative}' could not be read — {error}") from error


# -- module-level helpers ----------------------------------------------------


def _sequence(raw: Mapping[str, Any], key: str, case_name: str) -> list[Any]:
    value = raw.get(key) or []
    if not isinstance(value, list):
        raise DatasetError(f"{case_name}: '{key}' must be a list, not {type(value).__name__}.")
    return value


def _mapping(entry: Any, case_name: str, key: str) -> Mapping[str, Any]:
    if not isinstance(entry, Mapping):
        raise DatasetError(f"{case_name}: every '{key}' entry must be a mapping.")
    return entry


def _reject_unknown(mapping: Mapping[str, Any], allowed: frozenset[str], case_name: str, key: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise DatasetError(
            f"{case_name}: unknown key(s) {sorted(unknown)} in '{key}'. Allowed: {sorted(allowed)}."
        )


def _severity(raw: Any, case_name: str, rule: str) -> Severity | None:
    """Parsed strictly, unlike ``Severity.parse``.

    That method falls back to INFO because it reads policy files and model
    output, where a bad value should degrade a finding rather than abort a
    review. Here the value *is* the assertion, and silently turning
    ``severity: URGENT`` into INFO would invert what the case claims.
    """
    if raw is None:
        return None
    try:
        return Severity(str(raw).strip().lower())
    except ValueError as error:
        raise DatasetError(
            f"{case_name}: '{raw}' is not a severity for '{rule}'. "
            f"Use one of {[level.value for level in Severity]}."
        ) from error


def _scope(raw: Any, case_name: str) -> tuple[str, ...]:
    if raw is None:
        return (EVERYTHING,)
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return tuple(raw) or (EVERYTHING,)
    raise DatasetError(f"{case_name}: 'scope' must be a rule-id glob or a list of them.")


def _tolerance(raw: Any, case_name: str) -> int:
    if raw is None:
        return 0
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise DatasetError(f"{case_name}: 'line_tolerance' must be a whole number of lines, not '{raw}'.")
    return raw
