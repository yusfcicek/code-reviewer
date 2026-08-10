"""Building an index out of the checkout.

The one place in the retrieval pipeline that touches a filesystem, and it
touches it through :class:`Workspace` — the class that already states what this
project means by confinement: no path outside the root, no credential file at
any depth, a ceiling per file and a budget for the lot.

It gets its *own* workspace rather than sharing the review's. The budget exists
to bound an exfiltration one ordinary file at a time, and a review that spent
its whole allowance on indexing would have none left for the agent's actual
reads. Two budgets, two purposes.

Nothing here fails a review. A file that cannot be read is skipped with a log
line; a directory that does not exist yields an empty retriever that answers
every query with nothing. Retrieval is prompt material (decision D-5).
"""

import logging
import os
from pathlib import Path

from code_reviewer.application.ports import EmbeddingModel
from code_reviewer.application.retrieval_service import HybridRetriever
from code_reviewer.domain.retrieval import CodeChunk
from code_reviewer.infrastructure.tools.workspace import Workspace

from .chunking import chunk_source
from .embedding import HashingEmbedding
from .lexical import BM25Index
from .vector_index import InMemoryVectorIndex

logger = logging.getLogger(__name__)

#: What is worth indexing. Source and the configuration that changes how it
#: behaves; not images, not lock files, not anything generated.
INDEXABLE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".go",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".kt",
        ".rb",
        ".rs",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".sql",
        ".sh",
        ".yaml",
        ".yml",
        ".toml",
    }
)

#: Directories never worth walking. `.git` is refused by `Workspace` anyway;
#: the rest are here so a repository with a virtualenv in it does not spend a
#: minute indexing its dependencies.
SKIPPED_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".mypy_cache", ".tox"}
)

#: Ceilings. A repository that exceeds them gets a partial index rather than a
#: slow review, and says so in the log.
DEFAULT_MAX_FILES = 2_000
DEFAULT_MAX_CHUNKS = 20_000

#: Bytes the indexer may read in total. Separate from the review's budget.
DEFAULT_INDEX_BUDGET_BYTES = 32 * 1024 * 1024


def build_retriever(
    root: str | Path,
    embedding: EmbeddingModel | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> HybridRetriever:
    """Chunks and indexes every indexable file under ``root``.

    Returns a usable retriever whatever it found, including nothing.
    """
    model = embedding or HashingEmbedding()
    retriever = HybridRetriever(embedding=model, lexical=BM25Index(), vectors=InMemoryVectorIndex())

    chunks = collect_chunks(root, max_files=max_files, max_chunks=max_chunks)
    if chunks:
        retriever.index(chunks)
    logger.info("Indexed %d chunk(s) for retrieval", len(chunks))
    return retriever


def collect_chunks(
    root: str | Path,
    max_files: int = DEFAULT_MAX_FILES,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> list[CodeChunk]:
    """Every chunk of every indexable file, in a stable order."""
    # Resolved: `Workspace` resolves the paths it is given *against its root*,
    # so a relative root walked relatively produced `pkg/pkg/app.py`, every read
    # was refused, and the index came back empty — indistinguishable from a
    # repository with no source in it. Silent since Level 13 for any relative
    # root other than `.`, which is the default and the reason nobody saw it
    # (self-review 23, S-05).
    directory = Path(root).resolve()
    if not directory.is_dir():
        logger.warning("Nothing to index: '%s' is not a directory", directory)
        return []

    workspace = Workspace(directory, total_read_budget_bytes=DEFAULT_INDEX_BUDGET_BYTES)
    chunks: list[CodeChunk] = []
    files = 0

    for path in _indexable_files(directory):
        if files >= max_files or len(chunks) >= max_chunks:
            # Stated rather than silent: a truncated index that looks complete
            # is the kind of thing that gets diagnosed as "the model is bad".
            logger.warning(
                "Index truncated at %d file(s) and %d chunk(s); the repository is larger",
                files,
                len(chunks),
            )
            break

        source = _read(workspace, path)
        if source is None:
            continue

        files += 1
        relative = str(path.relative_to(directory))
        chunks.extend(chunk_source(relative, source))

    return chunks[:max_chunks]


# -- internals --------------------------------------------------------------


def _indexable_files(directory: Path) -> list[Path]:
    """Indexable files under ``directory``, sorted, skipping the noise.

    Walked with pruning rather than with ``rglob``, which enumerates every
    path before anything can filter it: on a checkout with a virtualenv in it
    that is tens of thousands of stats to discard tens of thousands of
    results, and it showed up as seventeen seconds in a unit test.
    """
    found: list[Path] = []
    for parent, directories, files in os.walk(directory):
        directories[:] = sorted(name for name in directories if name not in SKIPPED_DIRECTORIES)
        found.extend(Path(parent) / name for name in sorted(files) if Path(name).suffix in INDEXABLE_SUFFIXES)
    return found


def _read(workspace: Workspace, path: Path) -> str | None:
    """The file's text, or ``None`` for anything that cannot be indexed.

    Every refusal is one: a credential file the deny-list caught, a file over
    the per-file ceiling, a binary file that is not text at all, a read that
    failed. None of them is a reason to stop indexing the rest.
    """
    try:
        text = workspace.read(path)
    except Exception as error:
        logger.debug("Not indexing %s: %s", path, error)
        return None

    if _is_binary(text):
        logger.debug("Not indexing %s: it does not decode as text", path)
        return None
    return text


def _is_binary(text: str) -> bool:
    """Whether decoding produced rubble rather than source.

    `Workspace.read` replaces undecodable bytes rather than raising, which is
    the right behaviour for showing a file to a model and the wrong one for
    indexing: a `.py` that is actually a compiled artefact would become a
    chunk of replacement characters that matches every query weakly and no
    query well.
    """
    if "\x00" in text:
        return True
    return text.count("�") > max(1, len(text) // 100)
