"""Turning findings into suggestions, and refusing most of them.

The service is where the level's discipline lives. A recipe proposes; this
decides whether anybody gets to see it, and the default answer is no:

* a finding whose producer is not deterministic never yields one — Level 20's
  attribution, applied to a change that is one click from `main` (C-3);
* a suggestion is applied in memory and the result re-parsed, so an edit that
  would leave the file unparseable is discarded rather than published (C-2);
* two findings on one line yield at most one, because overlapping edits are not
  applicable and a reader cannot tell which button they clicked;
* nothing here raises. A review has already been paid for by the time this
  runs, and losing it to a regex is not a trade this project makes.

Note what is *not* checked: that the program means the same thing afterwards.
`md5` → `sha256` changes behaviour deliberately. What is checked is that the
edit is the one the recipe described and that the file still parses (D-3).
"""

import ast
import logging
from collections.abc import Sequence

from code_reviewer.application.governance import producer_for
from code_reviewer.domain.diffs import changed_lines
from code_reviewer.domain.finding import Finding
from code_reviewer.domain.fix_recipes import suggest
from code_reviewer.domain.remediation import Suggestion

logger = logging.getLogger(__name__)

#: Files a suggestion may be proposed for. The validation step is `ast.parse`,
#: so anything else would be discarded by it anyway — declining here says why
#: rather than looking like a parser bug.
SUGGESTABLE_SUFFIXES = (".py",)


class SuggestionService:
    """Proposes applicable edits for the findings that have a recipe.

    Args:
        version: The package version, for attributing a finding to its
            producer. The attribution table is Level 20's, and this is the
            second thing that reads it.
    """

    def __init__(self, version: str = ""):
        self._version = version

    def suggest_for(
        self, findings: Sequence[Finding], source: str, path: str = "", diff: str = ""
    ) -> tuple[Suggestion, ...]:
        """Every suggestion that survives validation, at most one per line.

        Args:
            findings: What the analyzers reported for this file.
            source: The file as reviewed. Empty means the forge could not
                return it, and an edit proposed against a file nobody read is
                a guess.
            path: The file the source belongs to. Findings about anything else
                are ignored: their line numbers mean nothing here.
            diff: What the merge request changed in it. Only lines this diff
                touched are eligible: a note cannot be anchored outside the
                diff, and an edit to untouched code is a change of subject
                rather than a fix (self-review S-02). Empty means "no diff was
                given", which leaves every line eligible — a diff that *was*
                given and cannot be read leaves none.
        """
        if not source:
            return ()

        subject = path or (findings[0].file_path if findings else "")
        if not subject.endswith(SUGGESTABLE_SUFFIXES):
            return ()

        eligible = changed_lines(diff) if diff else None
        if eligible is not None and not eligible:
            logger.warning(
                "Not proposing suggestions: no line of this file's diff could be read",
                extra={"fields": {"path": subject}},
            )
            return ()

        accepted: dict[int, Suggestion] = {}
        for finding in findings:
            if finding.file_path != subject:
                continue
            if eligible is not None and finding.line_number not in eligible:
                continue
            if not producer_for(finding.rule_id, self._version).is_deterministic:
                # An agent may not author an edit somebody will apply without
                # reading it, for the reason a model may not block a merge.
                continue
            if finding.line_number in accepted:
                continue

            suggestion = self._propose(finding, source)
            if suggestion is not None:
                accepted[finding.line_number] = suggestion

        return tuple(accepted[line] for line in sorted(accepted))

    # -- internals ----------------------------------------------------------

    def _propose(self, finding: Finding, source: str) -> Suggestion | None:
        """One finding's suggestion, if a recipe has one and it survives."""
        suggestion = suggest(finding, source)
        if suggestion is None:
            return None

        applied = suggestion.applied_to(source)
        if applied is None:
            logger.warning(
                "A suggestion did not fit the file it was proposed for; discarding it",
                extra={"fields": {"rule_id": finding.rule_id, "line": finding.line_number}},
            )
            return None

        try:
            ast.parse(applied)
        except SyntaxError as error:
            logger.warning(
                "A suggestion would leave the file unable to parse; discarding it",
                extra={"fields": {"rule_id": finding.rule_id, "error": str(error)}},
            )
            return None

        return suggestion


def render_suggestion(suggestion: Suggestion) -> str:
    """One suggestion, as a note the platform can turn into a change.

    The fenced ``suggestion:-a+b`` block is GitLab's: `a` lines above the
    anchor and `b` below are replaced by the block's contents. It is only
    applicable in a note attached to the line, which is why these go out as
    diff notes rather than as part of the review comment (contract C-6).

    The rule and the recipe are named above the block. A reader deciding
    whether to click should be able to see what proposed the edit without
    opening anything else.
    """
    lines = [
        f"**{suggestion.rule_id}** — suggested fix (`{suggestion.recipe}`).",
        "",
        f"```suggestion:-{suggestion.lines_above}+{suggestion.lines_below}",
        *suggestion.replacement,
        "```",
        "",
        "_Proposed by static analysis and validated against this file; it is applied only if you apply it._",
    ]
    return "\n".join(lines)
