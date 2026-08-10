"""A change somebody else can apply.

[Level 13](../../docs/roadmap/level-13/spec.md) left this out deliberately —
*"the agent reviews, it does not write the patch"* — and the reason it gave is
the reason this module is shaped the way it is. A patch a model generates and
something applies is a change nobody reviewed, inside a system whose whole
argument is that a model may not decide anything.

So a :class:`Suggestion` is a **proposal**: a replacement for a bounded range of
lines in one file, produced by a named deterministic recipe, rendered where a
human can apply it with one deliberate click. Nothing in this package writes a
file, runs `git`, or calls an API that changes a repository, and a test asserts
that rather than a sentence promising it (decision D-1).

Replacement *lines* rather than a unified diff: the platform wants lines and the
recipes produce lines, so a diff in between would be a format to generate and
then parse back — two directions to be wrong in (decision D-4).
"""

from dataclasses import dataclass
from itertools import pairwise

#: How many lines one suggestion may replace. Past a handful it is a refactor,
#: and a refactor arriving as a one-click button is how a reviewer stops
#: reading (contract C-5).
MAX_SUGGESTION_LINES = 12


@dataclass(frozen=True)
class SuggestionEdit:
    """One contiguous replacement inside a file.

    Level 26 split this out of :class:`Suggestion`. Level 22 shipped a
    suggestion as *one* range, and that excluded a whole shape of fix — the one
    that needs an import at the top and a call in the middle — by an accident of
    format rather than by judgement. Every guarantee that mattered was about
    validation, and validating a set is the same operation as validating one.
    """

    start_line: int
    end_line: int
    replacement: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.start_line < 1:
            raise ValueError(f"An edit starts at line {self.start_line}; files start at line 1.")
        if self.end_line < self.start_line:
            raise ValueError(
                f"An edit ends at line {self.end_line} and starts at {self.start_line}, which is not a range."
            )
        if not self.replacement:
            raise ValueError(
                f"The edit for lines {self.start_line}-{self.end_line} replaces them with nothing. "
                "Deleting code is a change worth writing by hand."
            )

    def overlaps(self, other: "SuggestionEdit") -> bool:
        return self.start_line <= other.end_line and other.start_line <= self.end_line

    def replaced_in(self, source: str) -> tuple[str, ...]:
        """The lines this would replace, or ``()`` if the range is not there."""
        lines = source.splitlines()
        if self.end_line > len(lines):
            return ()
        return tuple(lines[self.start_line - 1 : self.end_line])


@dataclass(frozen=True)
class Suggestion:
    """One applicable change, as a set of edits, and what proposed it.

    Args:
        rule_id: The finding this answers.
        file_path: The file it edits. One file, always — a suggestion is applied
            from one diff note on one file, so a cross-file suggestion is not
            something the platform can honour.
        edits: The replacements, each a contiguous range. They may not overlap:
            two edits claiming one line produce a result nobody can predict, and
            predicting it is the entire value of a one-click button.
        recipe: What produced it. Part of the value for the reason a producer is
            part of a claim in Level 20: "who decided this edit was right" is the
            question a reader asks second.
    """

    rule_id: str
    file_path: str
    edits: tuple[SuggestionEdit, ...]
    recipe: str

    def __post_init__(self) -> None:
        if not self.recipe.strip():
            raise ValueError("'something proposed this' is not provenance; a suggestion needs a recipe.")
        if not self.edits:
            raise ValueError("A suggestion with no edits changes nothing.")

        ordered = sorted(self.edits, key=lambda edit: edit.start_line)
        for earlier, later in pairwise(ordered):
            if earlier.overlaps(later):
                raise ValueError(
                    f"Two edits in the suggestion for {self.rule_id} claim lines "
                    f"{later.start_line}-{earlier.end_line}. Overlapping edits are refused rather "
                    "than resolved by ordering: the result depends on which is applied first."
                )

        total = sum(len(edit.replacement) for edit in self.edits)
        if total > MAX_SUGGESTION_LINES:
            raise ValueError(
                f"A suggestion may replace at most {MAX_SUGGESTION_LINES} lines in total; this one "
                f"has {total} across {len(self.edits)} edit(s). Past that it is a refactor rather "
                "than a fix."
            )

    @classmethod
    def single(
        cls,
        rule_id: str,
        file_path: str,
        start_line: int,
        end_line: int,
        replacement: tuple[str, ...],
        recipe: str,
    ) -> "Suggestion":
        """The Level 22 shape, which most recipes still want."""
        return cls(
            rule_id=rule_id,
            file_path=file_path,
            edits=(SuggestionEdit(start_line, end_line, tuple(replacement)),),
            recipe=recipe,
        )

    @property
    def anchor(self) -> SuggestionEdit:
        """The edit the note is posted on: the first, in file order."""
        return min(self.edits, key=lambda edit: edit.start_line)

    @property
    def start_line(self) -> int:
        return self.anchor.start_line

    @property
    def end_line(self) -> int:
        return self.anchor.end_line

    @property
    def replacement(self) -> tuple[str, ...]:
        return self.anchor.replacement

    @property
    def lines_above(self) -> int:
        """How far above the anchor the block reaches, in the platform's terms."""
        return 0

    @property
    def lines_below(self) -> int:
        return self.anchor.end_line - self.anchor.start_line

    def replaced_in(self, source: str) -> tuple[str, ...]:
        """What the anchoring edit would replace, or ``()``.

        Read by the service, which compares it against what the recipe said it
        matched: a recipe that matched line 4 and a file that has moved on are
        the same fact, and it means the suggestion is stale.
        """
        return self.anchor.replaced_in(source)

    def applied_to(self, source: str) -> str | None:
        """``source`` with every edit applied, or ``None`` if any does not fit.

        Applied **bottom-up**. Applying from the top invalidates every later
        line number, which is the arithmetic that is wrong once and then wrong
        everywhere, so it happens here and nowhere else.

        ``None`` rather than a partial application: a suggestion that silently
        lands some of its edits is one nobody can predict.
        """
        lines = source.splitlines()
        if any(edit.end_line > len(lines) for edit in self.edits):
            return None

        for edit in sorted(self.edits, key=lambda item: item.start_line, reverse=True):
            lines = [*lines[: edit.start_line - 1], *edit.replacement, *lines[edit.end_line :]]

        # The trailing newline is preserved rather than normalised: an edit that
        # silently strips one produces a diff nobody asked for.
        return "\n".join(lines) + ("\n" if source.endswith("\n") else "")
