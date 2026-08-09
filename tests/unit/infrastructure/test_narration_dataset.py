"""Step 4 — the corpus on disk, and what it refuses to load."""

import textwrap

import pytest

from code_reviewer.infrastructure.evaluation.narration_dataset import (
    NarrationCorpus,
    NarrationDatasetError,
)

CASE = """\
name: sql-injection
file: fixtures/sql_injection.py
prompt_fingerprint: b6b17025f0c5
findings:
  - rule: SAST.SQL_INJECTION
    line: 11
    severity: critical
    title: SQL Injection
review: |
  ## Security Analysis
  The SQL Injection at `fixtures/sql_injection.py:11` is CRITICAL.
"""


def _corpus(tmp_path, case: str = CASE, name: str = "sql-injection.yaml"):
    (tmp_path / "narration").mkdir(exist_ok=True)
    (tmp_path / "fixtures").mkdir(exist_ok=True)
    (tmp_path / "fixtures" / "sql_injection.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 41)), encoding="utf-8"
    )
    (tmp_path / "narration" / name).write_text(textwrap.dedent(case), encoding="utf-8")
    return NarrationCorpus(tmp_path)


# -- loading -----------------------------------------------------------------


def test_a_case_carries_its_review_and_the_facts_it_was_written_about(tmp_path):
    (case,) = _corpus(tmp_path).cases()

    assert case.name == "sql-injection"
    assert case.file_path == "fixtures/sql_injection.py"
    assert case.line_count == 40
    assert "SQL Injection" in case.review
    assert case.findings[0].rule_id == "SAST.SQL_INJECTION"
    assert case.prompt_fingerprint == "b6b17025f0c5"


def test_the_line_count_comes_from_the_fixture_rather_than_from_the_case(tmp_path):
    """A case that could state its own file's length could state one that
    makes its citations look grounded."""
    (case,) = _corpus(tmp_path).cases()

    assert case.line_count == 40


def test_cases_load_in_a_stable_order(tmp_path):
    corpus = _corpus(tmp_path)
    _corpus(tmp_path, CASE.replace("name: sql-injection", "name: another"), name="another.yaml")

    assert [case.name for case in corpus.cases()] == ["another", "sql-injection"]


# -- what it refuses ---------------------------------------------------------


def test_a_review_containing_a_credential_shaped_string_refuses_to_load(tmp_path):
    """The corpus holds text produced from real files. Four levels kept
    secrets out of the memory, the trace, the record and the comment; a
    corpus is not the place to let one back in (contract C-7)."""
    poisoned = CASE.replace("is CRITICAL.", "is CRITICAL. token glpat-ABCDEFGHIJKLMNOPQRST")

    with pytest.raises(NarrationDatasetError) as error:
        _corpus(tmp_path, poisoned).cases()

    assert "secret" in str(error.value).lower()
    assert "glpat-ABCDEFGHIJKLMNOPQRST" not in str(error.value)


def test_an_unknown_key_refuses_to_load(tmp_path):
    with pytest.raises(NarrationDatasetError) as error:
        _corpus(tmp_path, CASE + "notes: something\n").cases()

    assert "notes" in str(error.value)


def test_a_missing_fixture_refuses_to_load(tmp_path):
    with pytest.raises(NarrationDatasetError):
        _corpus(tmp_path, CASE.replace("fixtures/sql_injection.py", "fixtures/absent.py")).cases()


def test_a_case_with_no_review_refuses_to_load(tmp_path):
    with pytest.raises(NarrationDatasetError):
        _corpus(tmp_path, CASE.split("review:")[0]).cases()


def test_a_fixture_outside_the_corpus_refuses_to_load(tmp_path):
    """A case file arrives in a merge request, so its paths are untrusted in
    the ordinary sense."""
    with pytest.raises(NarrationDatasetError):
        _corpus(tmp_path, CASE.replace("fixtures/sql_injection.py", "../../etc/passwd")).cases()


def test_two_cases_with_one_name_refuse_to_load(tmp_path):
    corpus = _corpus(tmp_path)
    _corpus(tmp_path, CASE, name="duplicate.yaml")

    with pytest.raises(NarrationDatasetError) as error:
        corpus.cases()

    assert "sql-injection" in str(error.value)


def test_a_finding_without_a_severity_refuses_to_load(tmp_path):
    without = CASE.replace("    severity: critical\n", "")

    with pytest.raises(NarrationDatasetError):
        _corpus(tmp_path, without).cases()


def test_an_empty_corpus_directory_refuses_rather_than_scoring_zero(tmp_path):
    """Distinguishable from a corpus that scored badly: one is a broken
    harness and the other is a real measurement (contract C-9)."""
    (tmp_path / "narration").mkdir()

    with pytest.raises(NarrationDatasetError):
        NarrationCorpus(tmp_path).cases()
