"""S-02 — which lines of the new file a diff actually touched.

A suggestion is posted as a note with a position, and a position has to name a
line in the diff. Proposing an edit to a line the merge request never touched
produces a note the platform rejects — and it is the wrong thing to propose
anyway: an edit to untouched code is a change of subject rather than a fix.
"""

from code_reviewer.domain.diffs import changed_lines

# A context line for an empty line is a single space, which is why these are
# built by concatenation: a triple-quoted literal would have the whitespace
# stripped by the formatter and stop being a diff.
SIMPLE = "@@ -1,3 +1,4 @@\n import hashlib\n+import os\n \n def digest(value):\n"

TWO_HUNKS = (
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1,2 +1,3 @@\n"
    " import os\n"
    "+import sys\n"
    " \n"
    "@@ -10,3 +11,4 @@ def handler(request):\n"
    '     value = request.get("x")\n'
    "-    return md5(value)\n"
    "+    return sha256(value)\n"
    "     # trailing context\n"
)


def test_an_added_line_is_reported_at_its_new_number():
    assert changed_lines(SIMPLE) == frozenset({2})


def test_context_lines_are_not_changed_lines():
    """The whole point: a note on a context line is a note about code this
    merge request did not touch."""
    assert 1 not in changed_lines(SIMPLE)
    assert 3 not in changed_lines(SIMPLE)


def test_every_hunk_is_read_and_the_numbers_follow_the_new_file():
    assert changed_lines(TWO_HUNKS) == frozenset({2, 12})


def test_a_removal_contributes_no_new_line():
    """There is nothing to anchor a suggestion on: the line is gone."""
    removal = "@@ -1,3 +1,2 @@\n import os\n-import sys\n \n"

    assert changed_lines(removal) == frozenset()


def test_a_diff_with_no_hunk_header_yields_nothing():
    assert changed_lines("+ a line with no hunk\n") == frozenset()


def test_an_empty_diff_yields_nothing():
    assert changed_lines("") == frozenset()


def test_a_malformed_hunk_header_is_skipped_rather_than_raising():
    """A diff arrives from the forge, and a shape this cannot read is a
    reason to propose nothing rather than to lose the review."""
    assert changed_lines("@@ not a hunk @@\n+x = 1\n") == frozenset()


def test_a_hunk_without_a_line_count_is_read_as_one_line():
    """`@@ -1 +1 @@` is valid unified diff for a single-line hunk."""
    assert changed_lines("@@ -1 +7 @@\n-old\n+new\n") == frozenset({7})


def test_the_file_header_lines_are_not_counted_as_additions():
    """`+++ b/path` starts with a plus and is not a line of the file."""
    assert changed_lines(TWO_HUNKS) == frozenset({2, 12})
