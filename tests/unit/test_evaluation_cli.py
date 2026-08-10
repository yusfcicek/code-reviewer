"""Step 8 — the command, and the three things its exit code can mean."""

import json

import pytest

from code_reviewer.evaluate import _resolve_metric_floors, main
from code_reviewer.infrastructure.evaluation.narration_dataset import NarrationCorpus


def _dataset(root, case_body: str, fixture: str = "value = 1\n") -> str:
    (root / "cases").mkdir(parents=True, exist_ok=True)
    (root / "fixtures").mkdir(parents=True, exist_ok=True)
    (root / "fixtures" / "subject.py").write_text(fixture, encoding="utf-8")
    (root / "cases" / "case.yaml").write_text(case_body, encoding="utf-8")
    return str(root)


#: Floors of nothing, for the cases that exercise the plumbing rather than the
#: measurement. The default is now the floor the shipped corpus holds, and a
#: two-line dataset does not hold it (self-review 28, S-01).
NO_FLOOR = ["--min-precision", "0", "--min-recall", "0", "--min-f1", "0"]

CLEAN = "name: quiet\nfile: fixtures/subject.py\n"
UNMET = "name: silent\nfile: fixtures/subject.py\nexpect:\n  - rule: SAST.SQL_INJECTION\n    line: 1\n"


def test_a_dataset_meeting_every_floor_exits_zero(tmp_path, capsys):
    root = _dataset(tmp_path, CLEAN)

    # Floored at nothing on purpose. This dataset grades a fixture the suite
    # correctly stays quiet about, so it produces no true positives, no false
    # positives and nothing to be uncertain about — and since Level 25 a floor
    # is applied to the lower bound, which for a measurement of nothing is
    # zero. The shipped floor is what the shipped corpus holds and this is not
    # that corpus.
    code = main(["--dataset", root, *NO_FLOOR])

    assert code == 0
    assert "Evaluation" in capsys.readouterr().out


def test_a_dataset_that_measured_nothing_cannot_clear_a_floor(tmp_path, capsys):
    """ "The suite stayed quiet" is a correct result and not a measurement of
    accuracy. Before Level 25 it cleared any floor by dividing nothing by
    nothing; now the interval is [0, 1] and the message says why."""
    root = _dataset(tmp_path, CLEAN)

    code = main(["--dataset", root, "--min-precision", "0.5"])

    assert code == 1
    assert "too small to say" in capsys.readouterr().out


def test_a_score_below_a_floor_exits_one_and_names_the_shortfall(tmp_path, capsys):
    root = _dataset(tmp_path, UNMET)

    code = main(["--dataset", root, "--min-recall", "0.9"])

    assert code == 1
    output = capsys.readouterr().out
    assert "recall 0.00" in output
    assert "below the floor of 0.90" in output


def test_the_default_floor_is_the_one_the_shipped_corpus_holds(tmp_path):
    """Self-review 28, S-01.

    It used to be zero, so `ai-code-review-eval` with no arguments was a
    command that could not fail — and the workflow carried its own numbers,
    which is how they came to disagree with the code for four levels. The
    default is now the floor the corpus earned, and a run that misses it says
    so without being told to.
    """
    from code_reviewer.evaluate import DEFAULT_ANALYZER_FLOOR, DEFAULT_DOCUMENTATION_FLOOR, build_parser

    root = _dataset(tmp_path, UNMET)

    assert main(["--dataset", root]) == 1

    args = build_parser().parse_args(["--documentation"])
    _resolve_metric_floors(args)
    assert args.min_precision == DEFAULT_DOCUMENTATION_FLOOR

    args = build_parser().parse_args([])
    _resolve_metric_floors(args)
    assert args.min_precision == DEFAULT_ANALYZER_FLOOR


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

    assert main(["--dataset", root, "--json", str(destination), *NO_FLOOR]) == 0

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

    assert main(["--dataset", root, "--markdown", str(destination), *NO_FLOOR]) == 0
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


# -- Level 21: grading what the model said -----------------------------------
#
# One entry point rather than two: a team that runs one measurement in CI will
# run the second only if it costs a flag.

POOR_CASE = """\
name: hallucinating
file: fixtures/subject.py
review: |
  ## Security Analysis
  The problem is at `fixtures/elsewhere.py:900`.
"""


def _corpus(root, case_body: str = POOR_CASE) -> str:
    (root / "narration").mkdir(parents=True, exist_ok=True)
    (root / "fixtures").mkdir(parents=True, exist_ok=True)
    (root / "fixtures" / "subject.py").write_text("value = 1\n", encoding="utf-8")
    (root / "narration" / "case.yaml").write_text(case_body, encoding="utf-8")
    return str(root)


def test_the_shipped_corpus_is_graded_and_reported(capsys):
    code = main(["--narration", "--dataset", "evaluation"])

    assert code == 0
    output = capsys.readouterr().out
    assert "citations_are_grounded" in output
    assert f"{len(NarrationCorpus('evaluation').cases())} recorded review" in output


def test_a_floor_the_corpus_does_not_meet_exits_one(tmp_path, capsys):
    code = main(["--narration", "--dataset", _corpus(tmp_path), "--min-narration", "1.0"])

    assert code == 1


def test_a_corpus_that_cannot_be_read_exits_two(tmp_path, capsys):
    """Distinct from a low score: a pipeline that cannot tell a broken harness
    from a bad measurement has to treat both as advice."""
    code = main(["--narration", "--dataset", str(tmp_path / "absent")])

    assert code == 2


def test_the_report_names_the_failing_case_and_what_it_cited(tmp_path, capsys):
    main(["--narration", "--dataset", _corpus(tmp_path)])

    output = capsys.readouterr().out
    assert "hallucinating" in output
    assert "fixtures/elsewhere.py:900" in output


def test_stale_recordings_are_reported(capsys):
    """Every case shipped today was authored rather than recorded under a known
    prompt, and the report says so rather than letting the floor look better
    than it is."""
    main(["--narration", "--dataset", "evaluation"])

    assert "stale" in capsys.readouterr().out.lower()


def test_the_analyzer_grading_is_untouched_by_the_flag(capsys):
    """Two measurements, one command, and neither runs the other."""
    code = main(["--dataset", "evaluation"])

    assert code == 0
    assert "citations_are_grounded" not in capsys.readouterr().out


# -- S-05: a flag accepted and ignored ---------------------------------------


def test_the_narration_summary_is_written_where_json_asks_for_it(tmp_path, capsys):
    """`--json` was parsed, accepted and silently ignored on this path — the
    same shape as R-04 from the previous review, one level later."""
    destination = tmp_path / "narration.json"

    main(["--narration", "--dataset", "evaluation", "--json", str(destination)])

    written = json.loads(destination.read_text(encoding="utf-8"))
    assert written["cases"] >= 15
    assert 0.0 <= written["score"] <= 1.0
    assert "citations_are_grounded" in written["checks"]


def test_the_summary_names_the_stale_cases_rather_than_only_counting_them(tmp_path):
    destination = tmp_path / "narration.json"

    main(["--narration", "--dataset", "evaluation", "--json", str(destination)])

    written = json.loads(destination.read_text(encoding="utf-8"))
    assert isinstance(written["stale"], list)
    assert written["stale"], "every shipped case is authored, so every one is stale"


def test_a_summary_that_cannot_be_written_exits_two(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")

    code = main(["--narration", "--dataset", "evaluation", "--json", str(blocked / "x.json")])

    assert code == 2


class TestAlignment:
    """Level 29 — the fifth mode. Two texts, no model, no dataset."""

    def test_the_shipped_prompt_is_aligned_and_exits_zero(self, capsys):
        assert main(["--alignment"]) == 0

        output = capsys.readouterr().out
        assert "# Prompt and checks" in output
        assert "**Aligned**" in output

    def test_a_gap_exits_one(self, monkeypatch, capsys):
        """The exit code that means "a check grades a rule nobody asked for"."""
        from code_reviewer.infrastructure.llm.review_agent import ReviewAgent

        # Still demands the two headings nothing grades — otherwise the
        # declined notes would have outlived their sections, which is exit 2
        # and a different question.
        monkeypatch.setattr(
            ReviewAgent,
            "SYSTEM_TEMPLATE",
            "You are a reviewer.\n\n# Architectural Review Summary\n\n## Refactoring Roadmap\n",
        )

        assert main(["--alignment"]) == 1
        assert "NOT ALIGNED" in capsys.readouterr().out

    def test_a_declined_section_the_prompt_stopped_demanding_is_a_gap(self, monkeypatch, capsys):
        """Exit 1, not 2. Self-review 29, S-03: the measurement was taken and
        the answer is known — a note that outlived its section — so "could not
        measure" was the wrong thing for the command to say."""
        import code_reviewer.domain.narration as narration

        monkeypatch.setattr(narration, "UNCHECKED_SECTIONS", {"Vanished": "gone"})

        assert main(["--alignment"]) == 1
        assert "Vanished" in capsys.readouterr().out

    def test_a_graded_section_the_prompt_never_demands_is_a_gap(self, monkeypatch, capsys):
        """Self-review 29, S-01, at the command. Before it, this reported
        **Aligned** while every review would have failed forever."""
        import code_reviewer.domain.narration as narration

        monkeypatch.setattr(narration, "REQUIRED_SECTIONS", (*narration.REQUIRED_SECTIONS, "Threat Model"))

        assert main(["--alignment"]) == 1
        assert "Threat Model" in capsys.readouterr().out

    def test_a_constant_contradicting_another_cannot_be_measured(self, monkeypatch, capsys):
        """Exit 2 is kept for the case it was always right for: the code
        disagreeing with itself rather than with the prompt."""
        import code_reviewer.domain.narration as narration

        monkeypatch.setattr(narration, "UNCHECKED_SECTIONS", {"Code Quality": "a reason"})

        assert main(["--alignment"]) == 2
        assert "could not run" in capsys.readouterr().err

    def test_it_reads_no_dataset(self, tmp_path):
        """The other four modes need `--dataset`; this one measures the code
        that ships. Pointing it at an empty directory changes nothing."""
        assert main(["--alignment", "--dataset", str(tmp_path)]) == 0

    def test_the_report_can_be_written_to_a_file(self, tmp_path, capsys):
        destination = tmp_path / "alignment.md"

        assert main(["--alignment", "--markdown", str(destination)]) == 0
        assert "Prompt and checks" in destination.read_text(encoding="utf-8")
        assert capsys.readouterr().out == ""
