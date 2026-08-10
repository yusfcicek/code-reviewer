"""Splitting source into units worth retrieving.

A whole file is too coarse: retrieving one puts a thousand lines in a prompt to
answer a question about six of them. A fixed line window is too arbitrary: it
cuts functions in half, and half a function is evidence of nothing.

So Python is chunked by its syntax tree — each function, each class, and each
method both inside its class and on its own. The class answers *what is this
thing*, the method answers *how is this done*, and a retriever should be able
to return either.

Everything else — a file that does not parse, a YAML file, a half-written
branch — falls back to overlapping line windows. Overlapping, because a symbol
sitting on a window boundary would otherwise be split in every chunk that
contains it; with an overlap it is whole in one of them.
"""

import ast
import logging
import re

from code_reviewer.domain.retrieval import CodeChunk

logger = logging.getLogger(__name__)

#: Lines per window in the fallback. Roughly a screen: large enough to hold a
#: small function whole, small enough that retrieving one is not a paragraph of
#: unrelated context.
WINDOW_LINES = 40

#: How much consecutive windows share.
WINDOW_OVERLAP = 10


def chunk_source(
    path: str, source: str, window: int = WINDOW_LINES, overlap: int = WINDOW_OVERLAP
) -> list[CodeChunk]:
    """Every retrievable chunk of one file, in source order.

    Returns an empty list for a file with no content. Never raises: a file
    that cannot be chunked contributes nothing to the index, which is the same
    bargain every analyzer makes with a half-written branch.
    """
    if not source.strip():
        return []

    if path.endswith(".py"):
        chunks = _syntactic_chunks(path, source)
        if chunks:
            return chunks

    return _windows(path, source, window, overlap)


# -- internals --------------------------------------------------------------


def _syntactic_chunks(path: str, source: str) -> list[CodeChunk]:
    """Functions, classes and methods, or nothing if the file does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as error:
        logger.debug("Falling back to line windows for %s: %s", path, error)
        return []

    lines = source.splitlines()
    found: list[CodeChunk | None] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.append(_from_node(path, lines, node, node.name))
        elif isinstance(node, ast.ClassDef):
            found.append(_from_node(path, lines, node, node.name))
            found.extend(
                _from_node(path, lines, member, f"{node.name}.{member.name}")
                for member in node.body
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
            )

    # A module of imports and constants has no functions and is still worth
    # retrieving; without this, configuration modules are invisible.
    found.insert(0, _preamble(path, lines, tree))

    return [chunk for chunk in found if chunk is not None]


def _from_node(path: str, lines: list[str], node: ast.stmt, name: str) -> CodeChunk | None:
    """One chunk for one definition, starting at its first decorator."""
    decorators = getattr(node, "decorator_list", []) or []
    start = min([node.lineno, *(decorator.lineno for decorator in decorators)])
    end = getattr(node, "end_lineno", None) or node.lineno

    text = "\n".join(lines[start - 1 : end])
    if not text.strip():
        return None
    return CodeChunk(path=path, start_line=start, end_line=end, text=text, name=name)


def _preamble(path: str, lines: list[str], tree: ast.Module) -> CodeChunk | None:
    """Everything above the first definition: imports, constants, the docstring."""
    first_definition = next(
        (
            node.lineno
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        ),
        len(lines) + 1,
    )
    text = "\n".join(lines[: first_definition - 1])
    if not text.strip():
        return None
    return CodeChunk(
        path=path,
        start_line=1,
        end_line=first_definition - 1,
        text=text,
        name="",
    )


def _windows(path: str, source: str, window: int, overlap: int) -> list[CodeChunk]:
    """Overlapping fixed-size windows covering every line of ``source``."""
    lines = source.splitlines()
    step = max(1, window - overlap)

    chunks: list[CodeChunk] = []
    for start in range(0, len(lines), step):
        block = lines[start : start + window]
        if not block:
            break
        text = "\n".join(block)
        if text.strip():
            chunks.append(
                CodeChunk(
                    path=path,
                    start_line=start + 1,
                    end_line=start + len(block),
                    text=text,
                )
            )
        if start + window >= len(lines):
            break

    return chunks


#: Lines above which a section is split. A chapter-sized section is one chunk
#: that wins every query and spends the whole prompt budget by itself.
MAX_SECTION_LINES = 80

#: An ATX heading, outside a fence.
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*#*\s*$")

#: A fence. A `#` inside one is a shell comment, not a section.
_MARKDOWN_FENCE = re.compile(r"^\s*```")


def chunk_markdown(path: str, text: str, max_lines: int = MAX_SECTION_LINES) -> list[CodeChunk]:
    """Every retrievable section of one document, in document order.

    The sibling of :func:`chunk_source`, and for the same reason. A whole
    document retrieved to answer a question about one paragraph is a thousand
    lines of prompt for six lines of evidence; an arbitrary line window cuts a
    section in half, and half a section explains nothing.

    A section is a heading and everything under it until the next heading. The
    heading travels *with* the body because it is the section's subject — a
    retriever that returns the paragraph without "## Suppression" above it has
    returned an anonymous paragraph.

    Never raises. Prose before the first heading is kept as its own chunk, and
    a document with no heading at all is one chunk rather than none.
    """
    if not text.strip():
        return []

    chunks: list[CodeChunk] = []
    heading = ""
    start = 1
    body: list[str] = []
    fenced = False

    def flush() -> None:
        if any(line.strip() for line in body):
            chunks.extend(_section_chunks(path, heading, start, body, max_lines))

    for number, line in enumerate(text.splitlines(), start=1):
        if _MARKDOWN_FENCE.match(line):
            fenced = not fenced
        title = None if fenced else _MARKDOWN_HEADING.match(line)
        if title is None:
            body.append(line)
            continue

        flush()
        heading, start, body = title.group("title"), number, [line]

    flush()
    return chunks


def _section_chunks(path: str, heading: str, start: int, body: list[str], max_lines: int) -> list[CodeChunk]:
    """One section, split if it is long enough to dominate a result set."""
    if len(body) <= max_lines:
        return [
            CodeChunk(
                path=path,
                start_line=start,
                end_line=start + len(body) - 1,
                text="\n".join(body),
                name=heading,
            )
        ]

    pieces: list[CodeChunk] = []
    for offset in range(0, len(body), max_lines):
        window = body[offset : offset + max_lines]
        if not any(line.strip() for line in window):
            continue
        pieces.append(
            CodeChunk(
                path=path,
                start_line=start + offset,
                end_line=start + offset + len(window) - 1,
                text="\n".join(window),
                name=heading,
            )
        )
    return pieces
