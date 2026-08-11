"""The alignment measurement as markdown.

Deliberately without a ratio. Every other report in this repository prints a
number and an interval, because every other measurement is a sample; this one
compares two texts that ship together, so "three of five checks are unbacked" is
a list of three things to write and `0.40` would be a number pretending to be a
measurement (Level 29, decision D-2).

The sentence about the endpoint is printed on every run, in the same words, for
the same reason the retrieval report prints what it does not measure: a number
with no such sentence gets read as a verdict on the prose within a level.
"""

from code_reviewer.domain.alignment import AlignmentReport

#: Printed on every run. Two questions this measurement cannot answer, named
#: rather than approximated, because a prompt that *says* a thing and a model
#: that *does* it are different facts (Level 29, contract C-6).
NEEDS_AN_ENDPOINT = (
    "What this cannot tell you, and no amount of reading the prompt can: whether the model "
    "obeys an instruction that is present, and whether a recorded review still describes what "
    "the current prompt produces. Both need a served model on every iteration — the first is "
    "prompt tuning, the second is re-recording the corpus."
)


def render_alignment_report(report: AlignmentReport) -> str:
    """What the prompt and its checks say about each other, for a reader."""
    lines = [
        "# Prompt and checks",
        "",
        f"{len(report.aligned) + len(report.unbacked)} check(s) over the review prose, "
        f"{len(report.demanded)} heading(s) demanded by the output format.",
        "",
        f"**{'Aligned' if report.is_aligned else 'NOT ALIGNED'}** — "
        f"{len(report.unbacked)} unbacked check(s), {len(report.ungoverned)} ungoverned heading(s), "
        f"{len(report.ungrounded)} ungrounded name(s).",
        "",
    ]

    if report.ungrounded:
        lines += [
            "## Headings the code names and the prompt does not demand",
            "",
            "The damaging direction. A heading the checks require and the output format never "
            "asks for fails every review there will ever be; a reason recorded for a section the "
            "prompt dropped is a note that outlived its subject.",
            "",
            *[f"- {heading}" for heading in report.ungrounded],
            "",
        ]

    if report.unbacked:
        lines += [
            "## Checks the prompt never asks for",
            "",
            "A check with no instruction behind it grades the model on a rule it was never "
            "given. The fix is a sentence in the prompt, and the phrase that was looked for is "
            "the sentence.",
            "",
            "| check | not found in the prompt |",
            "|---|---|",
            *[
                f"| `{gap.check}` | {', '.join(f'`{phrase}`' for phrase in gap.missing)} |"
                for gap in report.unbacked
            ],
            "",
        ]

    if report.ungoverned:
        lines += [
            "## Headings nothing grades",
            "",
            "The output format demands these and no check looks for them, so a review that "
            "drops one passes everything.",
            "",
            *[f"- {heading}" for heading in report.ungoverned],
            "",
        ]

    if report.declined:
        lines += [
            "## Headings deliberately ungraded",
            "",
            *[f"- {heading}" for heading in report.declined],
            "",
        ]

    if report.aligned:
        lines += [
            "## Checks the prompt backs",
            "",
            *[f"- `{check}`" for check in report.aligned],
            "",
        ]

    lines += [f"_{NEEDS_AN_ENDPOINT}_", ""]
    return "\n".join(lines)
