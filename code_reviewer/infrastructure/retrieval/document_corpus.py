"""An index of the repository's prose, separate from the index of its code.

Self-review finding S-01. Level 23 shipped both in one index, on the strength of
its own non-goal — *"a second index would be a second thing to keep correct"* —
and the tier that depended on it returned **nothing at all**. Measured over this
repository: 4 205 code chunks against 1 129 document chunks, and 0 documents in
the top 20 for a realistic diff. Code wins every ranking, the limit is spent
before the service's document filter runs, and every candidate is discarded.

The non-goal was read too literally. What is worth not duplicating is the
retrieval *implementation* — the chunking, the fusion, the diversification, the
tests that pin them. A second *instance* of that implementation costs nothing to
keep correct, and it is the only way a document query returns documents.

Everything else about it matches `corpus.py`, deliberately: its own read budget,
its own workspace, and no failure that reaches the review.
"""

import logging
from pathlib import Path

from code_reviewer.application.ports import EmbeddingModel
from code_reviewer.application.retrieval_service import HybridRetriever
from code_reviewer.domain.retrieval import CodeChunk
from code_reviewer.infrastructure.documentation.workspace import collect_documents

from .chunking import chunk_markdown
from .corpus import DEFAULT_MAX_CHUNKS
from .embedding import HashingEmbedding
from .lexical import BM25Index
from .vector_index import InMemoryVectorIndex

logger = logging.getLogger(__name__)


def build_document_retriever(
    root: str | Path,
    embedding: EmbeddingModel | None = None,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> HybridRetriever:
    """Chunks and indexes every Markdown document under ``root``.

    Returns a usable retriever whatever it found, including nothing: a tree with
    no prose in it answers every query with an empty list, and the tier that
    asks contributes nothing rather than failing.
    """
    retriever = HybridRetriever(
        embedding=embedding or HashingEmbedding(),
        lexical=BM25Index(),
        vectors=InMemoryVectorIndex(),
    )

    chunks = collect_document_chunks(root, max_chunks=max_chunks)
    if chunks:
        retriever.index(chunks)
    logger.info("Indexed %d document section(s) for drift retrieval", len(chunks))
    return retriever


def collect_document_chunks(root: str | Path, max_chunks: int = DEFAULT_MAX_CHUNKS) -> list[CodeChunk]:
    """Every retrievable section of every document under ``root``."""
    chunks: list[CodeChunk] = []
    for path, text in collect_documents(root):
        if len(chunks) >= max_chunks:
            # Stated rather than silent, the rule `corpus.py` set: a truncated
            # index that looks complete gets diagnosed as "the model is bad".
            logger.warning("Document index truncated at %d section(s)", max_chunks)
            break
        chunks.extend(chunk_markdown(path, text))
    return chunks[:max_chunks]
