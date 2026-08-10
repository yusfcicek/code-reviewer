"""What the checkout offers, as names — and the documents that talk about it.

The I/O half of Level 23. Deciding what a backtick means is arithmetic and
lives in the domain; walking a tree, parsing it and reading Markdown off a disk
is not, and lives here.

It reads through :class:`Workspace` for the reason `corpus.py` gives: Level 8
bought path confinement with a class that states it, and a second traversal
that resolved its own paths would be re-implementing those guarantees without
the tests that pin them. It also takes its own read budget, because indexing
the tree and reviewing a merge request are two purposes and one allowance
spent on the first leaves nothing for the second.

Nothing here raises. A file that will not parse contributes no names; a
directory that is not there yields :data:`SymbolIndex.EMPTY`, which the rules
read as *unknown* rather than as *nothing exists*. That is the difference
between a quiet level and a level that reports every reference in every
document the first time a checkout is shallow.
"""

import ast
import logging
import os
from pathlib import Path

from code_reviewer.domain.documentation import SymbolIndex
from code_reviewer.infrastructure.tools.workspace import Workspace

from ..retrieval.corpus import DEFAULT_INDEX_BUDGET_BYTES, SKIPPED_DIRECTORIES

logger = logging.getLogger(__name__)

#: Documents this level reads. Markdown only: it is what this repository and
#: the ones it reviews write, and a format with a parser is a format whose
#: headings can be named in a finding.
DOCUMENT_SUFFIXES = frozenset({".md", ".markdown"})

#: Ceiling on files parsed for the index, matching `corpus.py`'s reasoning: a
#: partial index is a worse answer than a complete one and a much better answer
#: than a slow review.
DEFAULT_MAX_SOURCE_FILES = 2_000

#: Ceiling on documents read.
DEFAULT_MAX_DOCUMENTS = 500

#: Receivers whose subscript or `.get` reads an environment variable. Named
#: rather than assumed: `.get("key")` on an ordinary dictionary is not a read
#: of the environment, and collecting those keys would widen what the
#: unknown-option rule accepts until it accepted anything.
_ENVIRONMENT_READERS = frozenset({"environ", "env", "environment"})


def build_symbol_index(root: str | Path, max_files: int = DEFAULT_MAX_SOURCE_FILES) -> SymbolIndex:
    """Every name the Python tree under ``root`` defines, plus its options.

    Returns :data:`SymbolIndex.EMPTY` for a directory that is not there, which
    the rules treat as "nothing is known" rather than "nothing exists".
    """
    # Resolved: `Workspace` resolves the paths it is given *against its root*,
    # so a relative root and a relative walk produce `code_reviewer/…` under
    # `code_reviewer/`, which is outside the workspace and refused. Every path
    # from here down is absolute.
    directory = Path(root).resolve()
    if not directory.is_dir():
        logger.info("No symbol index: '%s' is not a directory", directory)
        return SymbolIndex.EMPTY

    workspace = Workspace(directory, total_read_budget_bytes=DEFAULT_INDEX_BUDGET_BYTES)
    collector = _Collector()

    for count, path in enumerate(_files_under(directory, {".py", ".pyi"})):
        if count >= max_files:
            logger.warning("Symbol index truncated at %d file(s); the repository is larger", max_files)
            break
        source = _read(workspace, path)
        if source is not None:
            collector.absorb(source, str(path.relative_to(directory)))

    return collector.index()


def collect_documents(root: str | Path, max_documents: int = DEFAULT_MAX_DOCUMENTS) -> list[tuple[str, str]]:
    """Every Markdown document under ``root``, as ``(relative path, text)``."""
    directory = Path(root).resolve()
    if not directory.is_dir():
        return []

    workspace = Workspace(directory, total_read_budget_bytes=DEFAULT_INDEX_BUDGET_BYTES)
    documents: list[tuple[str, str]] = []

    for path in _files_under(directory, DOCUMENT_SUFFIXES):
        if len(documents) >= max_documents:
            logger.warning("Document scan truncated at %d file(s)", max_documents)
            break
        text = _read(workspace, path)
        if text is not None:
            documents.append((str(path.relative_to(directory)), text))

    return documents


# -- internals --------------------------------------------------------------


class _Collector:
    """Accumulates names across files, then freezes them into an index."""

    def __init__(self) -> None:
        self._names: set[str] = set()
        self._signatures: dict[str, tuple[str, ...]] = {}
        self._options: set[str] = set()
        self._environment: set[str] = set()

    def index(self) -> SymbolIndex:
        return SymbolIndex(
            names=frozenset(self._names),
            signatures=dict(self._signatures),
            options=frozenset(self._options),
            environment=frozenset(self._environment),
        )

    def absorb(self, source: str, path: str) -> None:
        """Adds one file's names. A file that will not parse adds none."""
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError) as error:
            logger.debug("Not indexing names in %s: %s", path, error)
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._absorb_class(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._absorb_function(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                self._absorb_assignment(node)
            elif isinstance(node, ast.Call):
                self._absorb_call(node)
            elif isinstance(node, ast.Subscript):
                self._absorb_subscript(node)

    def _absorb_class(self, node: ast.ClassDef) -> None:
        self._names.add(node.name)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{node.name}.{child.name}"
                self._names.add(qualified)
                self._signatures[qualified] = _parameters(child)

    def _absorb_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._names.add(node.name)
        # A bare name may be defined twice — a method and a function, two
        # methods on two classes. The qualified entry is the precise one; this
        # is the convenience entry, and first writer wins so that a later
        # namesake cannot make an accurate document look wrong.
        self._signatures.setdefault(node.name, _parameters(node))

    def _absorb_assignment(self, node: ast.Assign | ast.AnnAssign) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                self._names.add(target.id)

    def _absorb_call(self, node: ast.Call) -> None:
        name = _attribute_name(node.func)
        if name == "add_argument":
            self._options.update(
                argument.value
                for argument in node.args
                if isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and argument.value.startswith("-")
            )
        elif self._reads_environment(node, name) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self._environment.add(first.value)

    @staticmethod
    def _reads_environment(node: ast.Call, name: str) -> bool:
        """`os.getenv(...)`, or `.get(...)` on something named like an environment.

        The receiver check is what keeps this from collecting the first
        argument of every `.get` in the repository. Those keys are dictionary
        keys, and treating them as environment variables would quietly widen
        what the unknown-option rule accepts until it accepted everything.
        """
        if name == "getenv":
            return True
        if name != "get" or not isinstance(node.func, ast.Attribute):
            return False
        return _attribute_name(node.func.value) in _ENVIRONMENT_READERS

    def _absorb_subscript(self, node: ast.Subscript) -> None:
        """`os.environ["NAME"]` — a literal key, never a computed one.

        A key built by concatenation is invisible to a parser, and collecting a
        guess for it would let the unknown-option rule report a name the code
        does read. Not collecting it costs recall and keeps the rule true.
        """
        if _attribute_name(node.value) not in _ENVIRONMENT_READERS:
            return
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            self._environment.add(node.slice.value)


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    arguments = node.args
    named = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    return tuple(argument.arg for argument in named if argument.arg not in ("self", "cls"))


def _attribute_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _files_under(directory: Path, suffixes: frozenset[str] | set[str]) -> list[Path]:
    """Matching files, sorted, walked with pruning.

    Pruned rather than globbed for the reason `corpus.py` records: `rglob`
    enumerates every path before anything can filter it, and on a checkout
    with a virtualenv in it that showed up as seventeen seconds in a test.
    """
    found: list[Path] = []
    for parent, directories, files in os.walk(directory):
        directories[:] = sorted(name for name in directories if name not in SKIPPED_DIRECTORIES)
        found.extend(Path(parent) / name for name in sorted(files) if Path(name).suffix in suffixes)
    return found


def _read(workspace: Workspace, path: Path) -> str | None:
    """The file's text, or ``None`` for anything that could not be read."""
    try:
        return workspace.read(path)
    except Exception as error:
        logger.debug("Not reading %s: %s", path, error)
        return None
