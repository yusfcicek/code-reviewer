"""Step 6 — reading a directory of annotated cases."""

import pytest

from code_reviewer.domain.severity import Severity
from code_reviewer.infrastructure.evaluation.dataset import DatasetError, FileSystemDataset


def _write_case(root, name: str, body: str) -> None:
    (root / "cases").mkdir(exist_ok=True)
    (root / "cases" / f"{name}.yaml").write_text(body, encoding="utf-8")


def _write_fixture(root, name: str, body: str = "pass\n") -> None:
    (root / "fixtures").mkdir(exist_ok=True)
    (root / "fixtures" / name).write_text(body, encoding="utf-8")


@pytest.fixture
def dataset_root(tmp_path):
    _write_fixture(tmp_path, "sql.py", "query = 'SELECT ' + name\n")
    _write_case(
        tmp_path,
        "sql-injection",
        """
        name: sql-injection
        file: fixtures/sql.py
        scope: ["SAST.*"]
        line_tolerance: 2
        expect:
          - rule: SAST.SQL_INJECTION
            line: 1
            severity: critical
        expect_absent:
          - rule: SAST.HARDCODED_SECRET
        """.replace("        ", ""),
    )
    return tmp_path


def test_a_case_directory_loads_into_fixtures(dataset_root):
    fixtures = FileSystemDataset(dataset_root).cases()

    assert len(fixtures) == 1
    case = fixtures[0].case
    assert case.name == "sql-injection"
    assert case.file_path == "fixtures/sql.py"
    assert case.scope == ("SAST.*",)
    assert case.line_tolerance == 2
    assert case.expected[0].rule_id == "SAST.SQL_INJECTION"
    assert case.expected[0].line_number == 1
    assert case.expected[0].severity is Severity.CRITICAL
    assert case.forbidden[0].rule_id == "SAST.HARDCODED_SECRET"
    assert case.forbidden[0].line_number == 0
    assert fixtures[0].content == "query = 'SELECT ' + name\n"
    assert fixtures[0].diff == ""


def test_cases_come_back_in_a_stable_order(dataset_root):
    for name in ("zebra", "alpha", "middle"):
        _write_case(dataset_root, name, f"name: {name}\nfile: fixtures/sql.py\n")

    names = [fixture.case.name for fixture in FileSystemDataset(dataset_root).cases()]

    assert names == sorted(names)


def test_a_case_may_supply_a_diff(dataset_root, tmp_path):
    (tmp_path / "fixtures" / "sql.diff").write_text("@@ -1 +1 @@\n", encoding="utf-8")
    _write_case(
        dataset_root,
        "with-diff",
        "name: with-diff\nfile: fixtures/sql.py\ndiff: fixtures/sql.diff\n",
    )

    fixtures = {fixture.case.name: fixture for fixture in FileSystemDataset(dataset_root).cases()}

    assert fixtures["with-diff"].diff == "@@ -1 +1 @@\n"


def test_the_default_scope_grades_everything(dataset_root):
    _write_case(dataset_root, "unscoped", "name: unscoped\nfile: fixtures/sql.py\n")

    fixtures = {fixture.case.name: fixture for fixture in FileSystemDataset(dataset_root).cases()}

    assert fixtures["unscoped"].case.scope == ("*",)


# -- what is refused ---------------------------------------------------------


def test_a_missing_fixture_names_the_path_and_the_case(dataset_root):
    _write_case(dataset_root, "absent", "name: absent\nfile: fixtures/nowhere.py\n")

    with pytest.raises(DatasetError) as error:
        FileSystemDataset(dataset_root).cases()

    assert "absent" in str(error.value)
    assert "fixtures/nowhere.py" in str(error.value)


def test_an_unknown_key_is_refused_rather_than_ignored(dataset_root):
    """The same fail-closed rule the policy loader follows (Level 9).

    A dataset is ground truth. A key nobody reads is a claim nobody checks,
    and here it would silently narrow what is being graded.
    """
    _write_case(dataset_root, "typo", "name: typo\nfile: fixtures/sql.py\nexpects: []\n")

    with pytest.raises(DatasetError) as error:
        FileSystemDataset(dataset_root).cases()

    assert "expects" in str(error.value)


def test_an_unknown_key_inside_an_expectation_is_refused(dataset_root):
    _write_case(
        dataset_root,
        "inner-typo",
        "name: inner-typo\nfile: fixtures/sql.py\nexpect:\n  - rule: A.B\n    lines: 3\n",
    )

    with pytest.raises(DatasetError) as error:
        FileSystemDataset(dataset_root).cases()

    assert "lines" in str(error.value)


def test_a_malformed_severity_is_refused(dataset_root):
    _write_case(
        dataset_root,
        "bad-severity",
        "name: bad-severity\nfile: fixtures/sql.py\n"
        "expect:\n  - rule: A.B\n    line: 1\n    severity: URGENT\n",
    )

    with pytest.raises(DatasetError) as error:
        FileSystemDataset(dataset_root).cases()

    assert "URGENT" in str(error.value)


def test_an_expectation_without_a_rule_is_refused(dataset_root):
    _write_case(dataset_root, "no-rule", "name: no-rule\nfile: fixtures/sql.py\nexpect:\n  - line: 3\n")

    with pytest.raises(DatasetError):
        FileSystemDataset(dataset_root).cases()


def test_an_expectation_without_a_line_is_refused(dataset_root):
    _write_case(dataset_root, "no-line", "name: no-line\nfile: fixtures/sql.py\nexpect:\n  - rule: A.B\n")

    with pytest.raises(DatasetError):
        FileSystemDataset(dataset_root).cases()


def test_a_case_file_that_is_not_a_mapping_is_refused(dataset_root):
    _write_case(dataset_root, "list", "- one\n- two\n")

    with pytest.raises(DatasetError) as error:
        FileSystemDataset(dataset_root).cases()

    assert "list" in str(error.value)


def test_a_case_without_a_file_is_refused(dataset_root):
    _write_case(dataset_root, "fileless", "name: fileless\n")

    with pytest.raises(DatasetError):
        FileSystemDataset(dataset_root).cases()


def test_unparseable_yaml_is_refused_with_the_file_named(dataset_root):
    _write_case(dataset_root, "broken", "name: [unclosed\n")

    with pytest.raises(DatasetError) as error:
        FileSystemDataset(dataset_root).cases()

    assert "broken" in str(error.value)


def test_a_fixture_path_escaping_the_root_is_refused(dataset_root, tmp_path):
    """A dataset is something a contributor opens a merge request against.

    Which makes a case file untrusted input, and `../` in it an attempt to
    read the host rather than the fixture.
    """
    (tmp_path.parent / "outside.py").write_text("secret\n", encoding="utf-8")
    _write_case(dataset_root, "escape", "name: escape\nfile: ../outside.py\n")

    with pytest.raises(DatasetError):
        FileSystemDataset(dataset_root).cases()


def test_a_root_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(DatasetError):
        FileSystemDataset(tmp_path / "nowhere").cases()


def test_a_root_with_no_cases_directory_is_refused(tmp_path):
    with pytest.raises(DatasetError):
        FileSystemDataset(tmp_path).cases()


def test_two_cases_sharing_a_name_are_refused(dataset_root):
    """Names key the report. Two rows called the same thing is a report that
    cannot be acted on."""
    _write_case(dataset_root, "duplicate", "name: sql-injection\nfile: fixtures/sql.py\n")

    with pytest.raises(DatasetError) as error:
        FileSystemDataset(dataset_root).cases()

    assert "sql-injection" in str(error.value)
