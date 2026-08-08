"""Step 4 — the retrievable unit."""

import pytest

from code_reviewer.domain.retrieval import CodeChunk


def _chunk(**overrides) -> CodeChunk:
    defaults = {
        "path": "a/b.py",
        "start_line": 10,
        "end_line": 24,
        "text": "def f():\n    return 1\n",
        "name": "f",
    }
    return CodeChunk(**{**defaults, **overrides})


def test_a_chunk_cites_where_it_came_from():
    assert _chunk().citation == "a/b.py:10-24"


def test_a_single_line_chunk_cites_one_line():
    assert _chunk(start_line=7, end_line=7).citation == "a/b.py:7"


def test_two_chunks_of_the_same_span_are_the_same_chunk():
    """A fused ranking deduplicates by value, so this has to hold."""
    assert _chunk() == _chunk()
    assert len({_chunk(), _chunk()}) == 1


def test_chunks_of_different_spans_are_different():
    assert _chunk() != _chunk(start_line=11)


def test_a_chunk_with_no_text_is_refused():
    """An index full of empty strings scores nothing and hides the chunker
    bug that produced it."""
    with pytest.raises(ValueError):
        _chunk(text="   \n\n")


def test_a_chunk_that_ends_before_it_starts_is_refused():
    with pytest.raises(ValueError):
        _chunk(start_line=20, end_line=10)


def test_the_name_is_optional():
    assert _chunk(name="").name == ""


def test_a_chunk_renders_as_its_citation_and_text():
    rendered = str(_chunk())

    assert "a/b.py:10-24" in rendered
    assert "return 1" in rendered
