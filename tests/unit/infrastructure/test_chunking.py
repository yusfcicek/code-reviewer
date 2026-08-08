"""Step 7 — splitting source into units worth retrieving."""

from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.infrastructure.retrieval.chunking import WINDOW_LINES, chunk_source

MODULE = '''"""A module."""

CONSTANT = 3


def free_function(value):
    """Doc."""
    return value + CONSTANT


class Holder:
    """A class."""

    def method(self, value):
        return free_function(value)

    def other(self):
        return 1
'''


def _by_name(chunks):
    return {chunk.name: chunk for chunk in chunks}


def test_a_module_chunks_into_its_functions_classes_and_methods():
    chunks = _by_name(chunk_source("m.py", MODULE))

    assert set(chunks) == {"", "free_function", "Holder", "Holder.method", "Holder.other"}
    # The unnamed one is the preamble: the docstring, the imports and the
    # module constants above the first definition.
    assert "CONSTANT = 3" in chunks[""].text


def test_a_chunk_spans_the_lines_its_symbol_occupies():
    chunks = _by_name(chunk_source("m.py", MODULE))

    assert (chunks["free_function"].start_line, chunks["free_function"].end_line) == (6, 8)
    assert chunks["Holder"].start_line == 11
    assert chunks["Holder.method"].start_line == 14


def test_a_chunk_carries_the_source_it_names():
    chunks = _by_name(chunk_source("m.py", MODULE))

    assert "def free_function(value):" in chunks["free_function"].text
    assert "return value + CONSTANT" in chunks["free_function"].text
    assert "def other" not in chunks["Holder.method"].text


def test_a_method_appears_inside_its_class_and_on_its_own():
    """Both are useful. The class answers 'what is this thing', the method
    answers 'how is this done', and a retriever should be able to return
    either."""
    chunks = _by_name(chunk_source("m.py", MODULE))

    assert "def method" in chunks["Holder"].text
    assert chunks["Holder.method"].text.strip().startswith("def method")


def test_a_decorated_function_chunk_starts_at_its_decorator():
    source = "@cache\ndef work():\n    return 1\n"

    chunk = chunk_source("m.py", source)[0]

    assert chunk.start_line == 1
    assert "@cache" in chunk.text


def test_module_level_code_is_not_lost():
    """A module of constants and imports has no functions, and is still worth
    retrieving. Losing it would make configuration modules invisible."""
    source = "import os\n\nSETTING = os.environ.get('X')\nOTHER = 2\n"

    chunks = chunk_source("m.py", source)

    assert chunks
    assert any("SETTING" in chunk.text for chunk in chunks)


def test_a_file_that_does_not_parse_falls_back_to_windows():
    source = "\n".join(f"line {index} def broken(:" for index in range(120))

    chunks = chunk_source("m.py", source)

    assert len(chunks) > 1
    assert all(chunk.name == "" for chunk in chunks)


def test_a_file_that_is_not_python_uses_windows():
    source = "\n".join(f"key{index} = value" for index in range(80))

    chunks = chunk_source("config.yaml", source)

    assert len(chunks) > 1


def test_windows_overlap_so_a_symbol_on_a_boundary_is_whole_somewhere():
    source = "\n".join(f"line {index}" for index in range(WINDOW_LINES * 2))

    chunks = chunk_source("x.txt", source)

    assert len(chunks) >= 2
    assert chunks[1].start_line < chunks[0].end_line


def test_an_empty_file_yields_nothing():
    assert chunk_source("m.py", "") == []
    assert chunk_source("m.py", "\n\n   \n") == []


def test_every_chunk_knows_its_path():
    for chunk in chunk_source("pkg/m.py", MODULE):
        assert chunk.path == "pkg/m.py"


@given(st.lists(st.text(alphabet="abc \t", min_size=0, max_size=12), min_size=1, max_size=200))
def test_windows_cover_every_line_of_the_input(lines):
    source = "\n".join(lines)
    chunks = chunk_source("x.txt", source)

    if not source.strip():
        assert chunks == []
        return

    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.start_line, chunk.end_line + 1))

    # Against `splitlines`, not against the input list: "a\n" is one line
    # with a terminator, and the chunker counts lines the way Python does.
    assert covered >= set(range(1, len(source.splitlines()) + 1))


@given(st.text(max_size=400))
def test_chunking_arbitrary_text_never_raises(text):
    for chunk in chunk_source("m.py", text):
        assert chunk.text.strip()
