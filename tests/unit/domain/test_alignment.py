"""Step 1 — whether the prompt asks for what the checks enforce.

Two texts and a substring search. Everything cleverer — a model asked whether
the prompt implies the rule, a similarity over embeddings — would put an
unmeasured judgement inside a measurement, which is the reason Level 21 refused
an LLM judge in the first place.
"""

import textwrap

import pytest

from code_reviewer.domain.alignment import (
    Expectation,
    Match,
    alignment,
    sections_demanded,
)

#: Dedented, like the shipped template. Four spaces of indentation make a
#: Markdown code block rather than a heading, and the reader of a prompt is
#: a Markdown renderer.
PROMPT = textwrap.dedent("""
    You are a reviewer.

    Cite every claim as `path:line`, and only lines that exist in the file.

    ## 🔒 Security Analysis
    - **Vulnerabilities Found**: [List or 'None']

    ## 📊 Code Quality
    - **SOLID Compliance**: [Score]

    ## 🛠️ Refactoring Roadmap
    ### [Priority] - [Title]
""")


class TestWhatTheOutputFormatDemands:
    def test_every_heading_is_found(self):
        assert sections_demanded(PROMPT) == (
            "Security Analysis",
            "Code Quality",
            "Refactoring Roadmap",
        )

    def test_the_decoration_is_not_part_of_the_name(self):
        """The format writes an emoji before each heading, and a check that
        pinned the decoration would fail on a change that means nothing —
        the reasoning `required_sections_are_present` already carries."""
        assert "🔒" not in " ".join(sections_demanded(PROMPT))

    def test_a_placeholder_heading_is_not_a_demand(self):
        """`### [Priority] - [Title]` is a template for a repeated block, not a
        section a review must contain. A check demanding it would demand the
        literal brackets."""
        assert not any(name.startswith("[") for name in sections_demanded(PROMPT))

    def test_a_prompt_with_no_headings_demands_nothing(self):
        assert sections_demanded("You are a reviewer. Be brief.") == ()


class TestAnExpectation:
    def test_all_phrases_must_appear(self):
        expectation = Expectation(check="cites", phrases=("path:line", "only lines that exist"))

        assert expectation.met_by(PROMPT)

    def test_one_missing_phrase_is_enough_to_miss(self):
        expectation = Expectation(check="cites", phrases=("path:line", "never invent a location"))

        assert not expectation.met_by(PROMPT)
        assert expectation.absent_from(PROMPT) == ("never invent a location",)

    def test_any_accepts_one_of_several_phrasings(self):
        expectation = Expectation(
            check="verdict", phrases=("never state a verdict", "do not approve"), match=Match.ANY
        )

        assert not expectation.met_by(PROMPT)

    def test_any_is_met_by_the_one_that_is_there(self):
        expectation = Expectation(check="cites", phrases=("path:line", "absent"), match=Match.ANY)

        assert expectation.met_by(PROMPT)
        assert expectation.absent_from(PROMPT) == ()

    def test_the_search_ignores_case_because_a_prompt_shouts(self):
        expectation = Expectation(check="cites", phrases=("CITE EVERY CLAIM",))

        assert expectation.met_by(PROMPT)

    def test_an_expectation_with_no_phrases_is_refused(self):
        """It would be met by every prompt, which is the shape of check this
        repository has caught itself building four times."""
        with pytest.raises(ValueError, match="phrase"):
            Expectation(check="empty", phrases=())


class TestTheReport:
    EXPECTATIONS = (
        Expectation(check="cites", phrases=("path:line",)),
        Expectation(check="no_verdict", phrases=("never state a verdict",)),
    )

    def test_a_check_the_prompt_says_nothing_about_is_unbacked(self):
        report = alignment(PROMPT, self.EXPECTATIONS, checked=(), declined={})

        assert [gap.check for gap in report.unbacked] == ["no_verdict"]
        assert report.unbacked[0].missing == ("never state a verdict",)

    def test_a_backed_check_is_aligned(self):
        report = alignment(PROMPT, self.EXPECTATIONS, checked=(), declined={})

        assert "cites" in report.aligned

    def test_a_demanded_heading_nothing_checks_is_ungoverned(self):
        report = alignment(PROMPT, self.EXPECTATIONS, checked=("Security Analysis",), declined={})

        assert report.ungoverned == ("Code Quality", "Refactoring Roadmap")

    def test_a_declined_heading_is_not_ungoverned(self):
        report = alignment(
            PROMPT,
            self.EXPECTATIONS,
            checked=("Security Analysis", "Code Quality"),
            declined={"Refactoring Roadmap": "the roadmap is advice, and advice is not a fact"},
        )

        assert report.ungoverned == ()
        assert report.declined == ("Refactoring Roadmap",)

    def test_a_decline_with_no_reason_is_refused(self):
        """The shape `fix_recipes.DECLINED` established: a refusal without a
        reason is indistinguishable from an oversight."""
        with pytest.raises(ValueError, match="reason"):
            alignment(PROMPT, self.EXPECTATIONS, checked=(), declined={"Code Quality": "  "})

    def test_a_declined_heading_the_prompt_does_not_demand_is_reported(self):
        """A reason for something nobody asked for is a reason that has gone
        stale — the prompt dropped the section and the note stayed.

        Reported rather than raised since self-review 29: the measurement was
        taken and the answer is known, so "could not measure" was the wrong
        thing for the command to say.
        """
        report = alignment(PROMPT, self.EXPECTATIONS, checked=(), declined={"Vanished": "gone"})

        assert report.ungrounded == ("Vanished",)

    def test_a_report_with_nothing_missing_is_aligned(self):
        report = alignment(
            PROMPT,
            (Expectation(check="cites", phrases=("path:line",)),),
            checked=("Security Analysis", "Code Quality", "Refactoring Roadmap"),
            declined={},
        )

        assert report.is_aligned
        assert not report.unbacked
        assert not report.ungoverned

    def test_a_report_with_a_gap_is_not_aligned(self):
        report = alignment(PROMPT, self.EXPECTATIONS, checked=(), declined={})

        assert not report.is_aligned

    def test_no_expectations_at_all_is_refused(self):
        """A measurement over nothing reports perfect alignment, which is the
        defect self-review 27 found in the retrieval corpus and 25 found in the
        analyzer harness. Twice is enough to write it down."""
        with pytest.raises(ValueError, match="expectation"):
            alignment(PROMPT, (), checked=(), declined={})


class TestANameInTheCodeThatThePromptDoesNotDemand:
    """Self-review 29, S-01 and S-03.

    The level validated the `declined` map against what the prompt demands and
    never validated `checked`. Adding a heading to `REQUIRED_SECTIONS` that the
    output format does not ask for makes every review fail
    `required_sections_are_present` forever — and the harness built to catch
    exactly that disagreement reported **Aligned**.

    It is the more damaging of the two directions. A demanded heading nothing
    grades costs a reader nothing; a graded heading nothing demands fails every
    case in the corpus.
    """

    EXPECTATIONS = (Expectation(check="cites", phrases=("path:line",)),)

    def test_a_graded_heading_the_prompt_never_demands_is_ungrounded(self):
        report = alignment(
            PROMPT, self.EXPECTATIONS, checked=("Security Analysis", "Threat Model"), declined={}
        )

        assert report.ungrounded == ("Threat Model",)
        assert not report.is_aligned

    def test_a_declined_heading_the_prompt_stopped_demanding_is_ungrounded_too(self):
        """It used to raise, so the command answered "the measurement could not
        be taken". The measurement was taken and the answer was known: a note
        that outlived its section. Same species, same list."""
        report = alignment(PROMPT, self.EXPECTATIONS, checked=(), declined={"Vanished": "gone"})

        assert "Vanished" in report.ungrounded
        assert not report.is_aligned

    def test_the_two_are_reported_together_in_reading_order(self):
        report = alignment(PROMPT, self.EXPECTATIONS, checked=("Zebra",), declined={"Aardvark": "a reason"})

        assert report.ungrounded == ("Aardvark", "Zebra")

    def test_a_heading_that_is_both_graded_and_declined_is_refused(self):
        """A contradiction between two constants, like a blank reason: it is
        a mistake in the code rather than a fact about the prompt."""
        with pytest.raises(ValueError, match="both"):
            alignment(
                PROMPT,
                self.EXPECTATIONS,
                checked=("Code Quality",),
                declined={"Code Quality": "a reason"},
            )

    def test_a_decline_with_no_reason_is_still_refused(self):
        with pytest.raises(ValueError, match="reason"):
            alignment(PROMPT, self.EXPECTATIONS, checked=(), declined={"Code Quality": "  "})
