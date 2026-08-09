"""Which lines of the new file a unified diff touched.

Small, and it exists for one reason. A suggestion is published as a note with a
position, and a position has to name a line **in the diff**: a note about an
untouched line is rejected by the platform, and the rejection arrives as a
warning nobody reads (self-review S-02).

It is also the wrong thing to propose. An edit to code this merge request did
not touch is a change of subject rather than a fix, however correct it is.

Parsing rather than trusting: the diff comes from the forge, and a shape this
cannot read is a reason to propose nothing rather than to lose the review.
"""

import re

#: `@@ -old[,count] +new[,count] @@`. The counts are optional — a single-line
#: hunk is written without one.
_HUNK = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(?P<start>\d+)(?:,(?P<count>\d+))?\s+@@")


def changed_lines(diff: str) -> frozenset[int]:
    """Line numbers, in the *new* file, that this diff added or changed.

    A removal contributes nothing: there is no line left to anchor anything on.
    """
    if not diff:
        return frozenset()

    touched: set[int] = set()
    cursor: int | None = None

    for line in diff.splitlines():
        header = _HUNK.match(line)
        if header is not None:
            cursor = int(header.group("start"))
            continue

        if cursor is None:
            # Text before the first hunk header: the `---`/`+++` file lines and
            # anything else the forge put there. Not lines of the file.
            continue

        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            touched.add(cursor)
            cursor += 1
        elif line.startswith("-"):
            # Gone from the new file, so the cursor does not move.
            continue
        else:
            # Context, including the empty string a trailing newline produces.
            cursor += 1

    return frozenset(touched)
