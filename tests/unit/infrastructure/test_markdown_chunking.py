"""Step 7a — documents as chunks, in the corpus that already exists.

`chunk_source` splits Python by its syntax tree because half a function is
evidence of nothing. A document has the same property and a different tree: a
section under a heading is the unit somebody wrote, and half of one answers no
question.
"""

from code_reviewer.infrastructure.retrieval.chunking import chunk_markdown

DOCUMENT = """# Title

Intro prose.

## Suppression

A directive silences a rule, and the reason is what the next person reads.

### Nested

Deeper still.

## Retrieval

Chunks are scored twice and fused by rank.
"""


def _named(text):
    return {chunk.name: chunk for chunk in chunk_markdown("docs/guide.md", text)}


def test_each_heading_starts_a_chunk():
    assert set(_named(DOCUMENT)) == {"Title", "Suppression", "Nested", "Retrieval"}


def test_a_chunk_keeps_its_heading_with_its_body():
    chunk = _named(DOCUMENT)["Suppression"]

    assert "## Suppression" in chunk.text
    assert "the reason is what the next person reads" in chunk.text


def test_a_chunk_stops_at_the_next_heading():
    chunk = _named(DOCUMENT)["Suppression"]

    assert "Deeper still" not in chunk.text
    assert "fused by rank" not in chunk.text


def test_chunks_carry_their_line_range():
    chunk = _named(DOCUMENT)["Suppression"]

    assert chunk.start_line == 5
    assert chunk.end_line < 11


def test_the_path_travels_with_the_chunk():
    assert all(chunk.path == "docs/guide.md" for chunk in chunk_markdown("docs/guide.md", DOCUMENT))


def test_prose_before_the_first_heading_is_kept():
    chunks = chunk_markdown("docs/guide.md", "Loose prose.\n\n# Title\n\nUnder it.\n")

    assert any("Loose prose." in chunk.text for chunk in chunks)


def test_a_document_with_no_heading_still_chunks():
    """AC-10's other half: a README that never uses `#` is still retrievable."""
    chunks = chunk_markdown("docs/guide.md", "Just prose, no headings anywhere.\n")

    assert len(chunks) == 1
    assert chunks[0].name == ""


def test_an_empty_document_yields_nothing():
    assert chunk_markdown("docs/guide.md", "") == []
    assert chunk_markdown("docs/guide.md", "\n\n   \n") == []


def test_a_heading_with_an_empty_section_yields_no_chunk():
    """A chunk must have text; a heading with nothing under it has none worth
    retrieving, and `CodeChunk` refuses an empty one anyway."""
    chunks = chunk_markdown("docs/guide.md", "# One\n\n# Two\n\nBody.\n")

    assert [chunk.name for chunk in chunks] == ["One", "Two"]


def test_a_heading_inside_a_fence_is_not_a_heading():
    """A shell comment in a fenced block starts with `#` and is not a section."""
    text = "# Title\n\n```bash\n# not a heading\necho hi\n```\n\n## Real\n\nBody.\n"

    assert [chunk.name for chunk in chunk_markdown("docs/guide.md", text)] == ["Title", "Real"]


def test_a_very_long_section_is_split_rather_than_returned_whole():
    """A section the size of a chapter is one chunk that wins every query and
    fills the budget on its own."""
    text = "# Title\n\n" + "".join(f"line {number}\n" for number in range(400))

    chunks = chunk_markdown("docs/guide.md", text)

    assert len(chunks) > 1
    assert all(chunk.text.count("\n") <= 120 for chunk in chunks)
