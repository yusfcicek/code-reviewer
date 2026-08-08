"""Step 8 — the command, and the three things its exit code can mean."""

import json

import pytest

from code_reviewer.evaluate import main


def _dataset(root, case_body: str, fixture: str = "value = 1\n") -> str:
    (root / "cases").mkdir(parents=True, exist_ok=True)
    (root / "fixtures").mkdir(parents=True, exist_ok=True)
    (root / "fixtures" / "subject.py").write_text(fixture, encoding="utf-8")
    (root / "cases" / "case.yaml").write_text(case_body, encoding="utf-8")
    return str(root)


CLEAN = "name: quiet\nfile: fixtures/subject.py\n"
UNMET = "name: silent\nfile: fixtures/subject.py\nexpect:\n  - rule: SAST.SQL_INJECTION\n    line: 1\n"


def test_a_dataset_meeting_every_floor_exits_zero(tmp_path, capsys):
    root = _dataset(tmp_path, CLEAN)

    code = main(["--dataset", root, "--min-precision", "0.9", "--min-recall", "0.9", "--min-f1", "0.9"])

    assert code == 0
    assert "Evaluation" in capsys.readouterr().out


def test_a_score_below_a_floor_exits_one_and_names_the_shortfall(tmp_path, capsys):
    root = _dataset(tmp_path, UNMET)

    code = main(["--dataset", root, "--min-recall", "0.9"])

    assert code == 1
    assert "recall 0.00 is below the floor of 0.90" in capsys.readouterr().out


def test_the_default_floors_are_zero_so_a_run_reports_without_gating(tmp_path):
    root = _dataset(tmp_path, UNMET)

    assert main(["--dataset", root]) == 0


def test_a_missing_fixture_exits_two_and_names_the_case(tmp_path, capsys):
    root = _dataset(tmp_path, "name: absent\nfile: fixtures/nowhere.py\n")

    code = main(["--dataset", root])

    assert code == 2
    assert "absent" in capsys.readouterr().err


def test_a_dataset_that_is_not_there_exits_two(tmp_path, capsys):
    code = main(["--dataset", str(tmp_path / "nowhere")])

    assert code == 2
    assert "nowhere" in capsys.readouterr().err


def test_the_json_summary_is_written_where_asked(tmp_path):
    root = _dataset(tmp_path, CLEAN)
    destination = tmp_path / "out" / "evaluation.json"

    assert main(["--dataset", root, "--json", str(destination)]) == 0

    summary = json.loads(destination.read_text(encoding="utf-8"))
    assert summary["cases"] == 1
    assert summary["overall"]["precision"] == 1.0


def test_the_json_summary_is_written_even_when_the_run_fails_its_floor(tmp_path):
    """The artefact is the series. A run that is missing exactly when the
    numbers got worse is a series with a hole where the regression was."""
    root = _dataset(tmp_path, UNMET)
    destination = tmp_path / "evaluation.json"

    assert main(["--dataset", root, "--min-f1", "0.9", "--json", str(destination)]) == 1
    assert json.loads(destination.read_text(encoding="utf-8"))["shortfalls"]


def test_the_markdown_can_be_written_to_a_file(tmp_path, capsys):
    root = _dataset(tmp_path, CLEAN)
    destination = tmp_path / "evaluation.md"

    assert main(["--dataset", root, "--markdown", str(destination)]) == 0
    assert "# Evaluation" in destination.read_text(encoding="utf-8")
    assert capsys.readouterr().out == ""


def test_an_unwritable_json_destination_exits_two(tmp_path, capsys):
    root = _dataset(tmp_path, CLEAN)

    code = main(["--dataset", root, "--json", str(tmp_path / "fixtures" / "subject.py" / "x.json")])

    assert code == 2
    assert capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--min-precision", "--min-recall", "--min-f1"])
def test_a_floor_outside_zero_to_one_is_rejected(tmp_path, flag, capsys):
    root = _dataset(tmp_path, CLEAN)

    with pytest.raises(SystemExit) as exit_info:
        main(["--dataset", root, flag, "1.5"])

    assert exit_info.value.code == 2
    assert "between 0 and 1" in capsys.readouterr().err


def test_defaults_come_from_the_environment(tmp_path, monkeypatch):
    root = _dataset(tmp_path, UNMET)
    monkeypatch.setenv("EVALUATION_DATASET", root)
    monkeypatch.setenv("EVALUATION_MIN_F1", "0.9")

    assert main([]) == 1


def test_the_shipped_dataset_is_the_default_when_nothing_says_otherwise(monkeypatch):
    monkeypatch.delenv("EVALUATION_DATASET", raising=False)
    from code_reviewer.evaluate import build_parser

    assert build_parser().parse_args([]).dataset == "evaluation"
