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

#: How many lines one suggestion may replace. Past a handful it is a refactor,
#: and a refactor arriving as a one-click button is how a reviewer stops
#: reading (contract C-5).
MAX_SUGGESTION_LINES = 12


@dataclass(frozen=True)
class Suggestion:
    """One applicable edit, and what proposed it.

    Args:
        rule_id: The finding this answers.
        file_path: The file it edits. One file, always: a change spanning two
            is a merge request rather than a suggestion.
        start_line: First line replaced, 1-based and inclusive.
        end_line: Last line replaced, inclusive.
        replacement: The lines that take their place, without line endings.
        recipe: What produced it. Part of the value for the reason a producer
            is part of a claim in Level 20: "who decided this edit was right"
            is the question a reader asks second.
    """

    rule_id: str
    file_path: str
    start_line: int
    end_line: int
    replacement: tuple[str, ...]
    recipe: str

    def __post_init__(self) -> None:
        if not self.recipe.strip():
            raise ValueError("'something proposed this' is not provenance; a suggestion needs a recipe.")
        if self.start_line < 1:
            raise ValueError(f"A suggestion starts at line {self.start_line}; files start at line 1.")
        if self.end_line < self.start_line:
            raise ValueError(
                f"A suggestion for {self.file_path} ends at line {self.end_line} and starts at "
                f"{self.start_line}, which is not a range."
            )
        if not self.replacement:
            raise ValueError(
                f"The suggestion for {self.rule_id} replaces lines {self.start_line}-{self.end_line} "
                "with nothing. Deleting code is a change worth writing by hand."
            )
        if len(self.replacement) > MAX_SUGGESTION_LINES:
            raise ValueError(
                f"A suggestion may replace at most {MAX_SUGGESTION_LINES} lines; this one has "
                f"{len(self.replacement)}. Past that it is a refactor rather than a fix."
            )

    @property
    def lines_above(self) -> int:
        """How far above the anchor the block reaches, in the platform's terms."""
        return 0

    @property
    def lines_below(self) -> int:
        return self.end_line - self.start_line

    def replaced_in(self, source: str) -> tuple[str, ...]:
        """The lines this would replace, or ``()`` if the range is not there.

        Read by the service, which compares them against what the recipe said
        it matched: a recipe that matched line 4 and a file that has moved on
        are the same fact, and it means the suggestion is stale.
        """
        lines = source.splitlines()
        if self.end_line > len(lines):
            return ()
        return tuple(lines[self.start_line - 1 : self.end_line])

    def applied_to(self, source: str) -> str | None:
        """``source`` with the range replaced, or ``None`` if it does not fit.

        ``None`` rather than a truncated edit: a suggestion that silently
        applies to fewer lines than it claimed is one nobody can predict, and
        predicting it is the entire value of a one-click button.
        """
        lines = source.splitlines()
        if self.end_line > len(lines):
            return None

        edited = [*lines[: self.start_line - 1], *self.replacement, *lines[self.end_line :]]
        # The trailing newline is preserved rather than normalised: an edit that
        # silently strips one produces a diff nobody asked for.
        return "\n".join(edited) + ("\n" if source.endswith("\n") else "")
