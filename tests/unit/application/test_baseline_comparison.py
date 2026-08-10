"""Step 7 — a baseline that names what produced it, and a delta with a subject.

"Is this better than last week" needs two things this repository did not have:
a stored measurement, and something that says *what differed between the runs*.
A delta between two numbers whose provenance nobody recorded is a number
without a subject.

The refusal is the important part. Two runs over different case sets are not
comparable, and reporting their difference as movement would be the most
confident wrong number this repository could produce.
"""

from code_reviewer.application.baselines import (
    NarrationBaseline,
    baseline_from,
    compare,
    read_baseline,
    render_comparison,
    write_baseline,
)
from code_reviewer.application.narration_evaluation import NarrationEvaluator
from code_reviewer.domain.narration import NarrationCase

CLEAN = """## 🔒 Security Analysis
- **SAST Scan Result**: PASS

## 🔍 Semantic Change Analysis
- **Change Type**: REFACTOR

## 🔗 Impact Analysis
- **Dependencies Checked**: `fixtures/subject.py`

## 📊 Code Quality
- **SOLID Compliance**: 90/100

## ⚡ Performance Analysis
- **Complexity Issues**: None
"""

VERDICT = CLEAN + "\nI reject this merge request.\n"


def _case(name, review=CLEAN, expected_failures=()):
    return NarrationCase(
        name=name,
        file_path="fixtures/subject.py",
        line_count=20,
        review=review,
        findings=(),
        expected_failures=tuple(expected_failures),
    )


def _report(*cases):
    return NarrationEvaluator().evaluate(cases)


def _baseline(*cases, model="qwen3-8b", fingerprint="aaaaaaaaaaaa"):
    return baseline_from(
        _report(*cases), model=model, prompt_fingerprint=fingerprint, recorded_at="2026-08-01T00:00:00+00:00"
    )


class TestWhatABaselineCarries:
    def test_it_names_the_model(self):
        assert _baseline(_case("a")).model == "qwen3-8b"

    def test_it_names_the_prompt_that_produced_it(self):
        """AC-13. A baseline that cannot say which prompt made it cannot
        support a delta about a prompt change."""
        assert _baseline(_case("a")).prompt_fingerprint == "aaaaaaaaaaaa"

    def test_it_names_the_cases(self):
        assert _baseline(_case("a"), _case("b")).case_names == ("a", "b")

    def test_it_carries_a_rate_for_every_check(self):
        from code_reviewer.domain.narration import CHECK_NAMES

        assert set(_baseline(_case("a")).rates) == set(CHECK_NAMES)

    def test_it_carries_the_overall_score(self):
        assert _baseline(_case("a")).score == 1.0

    def test_it_carries_when_it_was_taken(self):
        assert _baseline(_case("a")).recorded_at.startswith("2026-08-01")


class TestStoringIt:
    def test_a_written_baseline_reads_back_the_same(self, tmp_path):
        path = tmp_path / "baseline.json"
        original = _baseline(_case("a"), _case("b"))

        write_baseline(path, original)

        assert read_baseline(path) == original

    def test_a_missing_baseline_reads_as_nothing_rather_than_raising(self, tmp_path):
        assert read_baseline(tmp_path / "absent.json") is None

    def test_a_malformed_baseline_reads_as_nothing(self, tmp_path):
        path = tmp_path / "baseline.json"
        path.write_text("not json", encoding="utf-8")

        assert read_baseline(path) is None


class TestTheComparison:
    def test_a_check_that_fell_is_named(self):
        before = _baseline(_case("a"))
        after = _report(_case("a", review=VERDICT, expected_failures=[]))

        comparison = compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa")

        assert [movement.check for movement in comparison.fell] == ["the_prose_claims_no_verdict"]

    def test_a_check_that_rose_is_named(self):
        before = _baseline(_case("a", review=VERDICT))
        after = _report(_case("a"))

        comparison = compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa")

        assert [movement.check for movement in comparison.rose] == ["the_prose_claims_no_verdict"]

    def test_movement_carries_both_numbers(self):
        before = _baseline(_case("a"))
        after = _report(_case("a", review=VERDICT))

        movement = compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa").fell[0]

        assert movement.before == 1.0
        assert movement.after == 0.0

    def test_an_unchanged_run_reports_no_movement(self):
        before = _baseline(_case("a"))
        after = _report(_case("a"))

        comparison = compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa")

        assert comparison.rose == ()
        assert comparison.fell == ()


class TestWhatItRefusesToCompare:
    def test_two_different_case_sets_are_refused(self):
        """AC-15, and the most confident wrong number this repository could
        produce."""
        before = _baseline(_case("a"), _case("b"))
        after = _report(_case("a"), _case("c"))

        comparison = compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa")

        assert comparison.refused
        assert comparison.fell == ()

    def test_the_refusal_names_what_differs(self):
        before = _baseline(_case("a"), _case("b"))
        after = _report(_case("a"), _case("c"))

        comparison = compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa")

        assert "b" in comparison.refused
        assert "c" in comparison.refused

    def test_a_reordered_case_set_is_still_the_same_corpus(self):
        before = _baseline(_case("a"), _case("b"))
        after = _report(_case("b"), _case("a"))

        assert compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa").refused == ""


class TestNamingWhatChanged:
    def test_a_different_prompt_is_compared_and_labelled(self):
        """AC-16 — this is the comparison somebody actually wants, with the
        thing that changed named."""
        before = _baseline(_case("a"))
        after = _report(_case("a"))

        comparison = compare(before, after, model="qwen3-8b", prompt_fingerprint="bbbbbbbbbbbb")

        assert comparison.refused == ""
        assert comparison.prompt_changed

    def test_a_different_model_is_labelled_too(self):
        before = _baseline(_case("a"))
        after = _report(_case("a"))

        comparison = compare(before, after, model="other-model", prompt_fingerprint="aaaaaaaaaaaa")

        assert comparison.model_changed

    def test_nothing_changed_is_labelled_as_nothing_changed(self):
        before = _baseline(_case("a"))
        after = _report(_case("a"))

        comparison = compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa")

        assert not comparison.prompt_changed
        assert not comparison.model_changed


class TestRendering:
    def _rendered(self, prompt_fingerprint="bbbbbbbbbbbb"):
        before = _baseline(_case("a"))
        after = _report(_case("a", review=VERDICT))
        return render_comparison(
            compare(before, after, model="qwen3-8b", prompt_fingerprint=prompt_fingerprint)
        )

    def test_it_names_the_checks_that_moved(self):
        assert "the_prose_claims_no_verdict" in self._rendered()

    def test_it_says_the_prompt_changed(self):
        assert "prompt" in self._rendered().lower()

    def test_it_does_not_reduce_the_run_to_one_number(self):
        """AC-14 — 'better' is not a scalar."""
        rendered = self._rendered().lower()

        assert "check" in rendered

    def test_a_refusal_renders_as_a_refusal(self):
        before = _baseline(_case("a"))
        after = _report(_case("z"))

        rendered = render_comparison(
            compare(before, after, model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa")
        )

        assert "not comparable" in rendered.lower()


def test_a_baseline_can_be_built_directly():
    baseline = NarrationBaseline(
        model="m", prompt_fingerprint="f", case_names=("a",), rates={"x": 1.0}, score=1.0, recorded_at="t"
    )

    assert baseline.rates["x"] == 1.0


class TestAChecksetThatChanged:
    """Self-review S-03 — a rise from nothing.

    `rates.get(check, 0.0)` read a check the baseline never measured as a rate
    of zero, so adding a check to the corpus rendered as the reviewer improving
    on four fronts at once. The same error the level refused elsewhere —
    attributing a corpus edit to the thing being measured — and it slipped
    through because the refusal compared case names and nothing compared check
    names.
    """

    def _old_baseline(self):
        return NarrationBaseline(
            model="qwen3-8b",
            prompt_fingerprint="aaaaaaaaaaaa",
            case_names=("a",),
            rates={"citations_are_grounded": 1.0},
            score=1.0,
            recorded_at="2026-08-01T00:00:00+00:00",
        )

    def test_a_check_the_baseline_never_measured_is_not_movement(self):
        comparison = compare(
            self._old_baseline(), _report(_case("a")), model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa"
        )

        assert comparison.rose == ()

    def test_it_is_reported_as_new_instead(self):
        comparison = compare(
            self._old_baseline(), _report(_case("a")), model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa"
        )

        assert "the_prose_claims_no_verdict" in comparison.unmeasured

    def test_the_checks_both_runs_measured_still_compare(self):
        comparison = compare(
            self._old_baseline(), _report(_case("a")), model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa"
        )

        assert [movement.check for movement in comparison.unchanged] == ["citations_are_grounded"]

    def test_the_rendering_names_the_new_checks(self):
        comparison = compare(
            self._old_baseline(), _report(_case("a")), model="qwen3-8b", prompt_fingerprint="aaaaaaaaaaaa"
        )

        assert "the_prose_claims_no_verdict" in render_comparison(comparison)
