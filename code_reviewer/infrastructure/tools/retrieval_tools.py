"""The tool that searches the repository index.

Its own module rather than a seventh class in `definitions.py`. That file was
already five tool classes and four hundred lines; adding this one took its
quality score below the gate's threshold, and the agent reported it against its
own source before the change was committed. Splitting it is the fix the finding
asked for.

The retriever is held in a module global, set by the composition root, the same
shape `set_workspace` uses and for the same reason: a LangChain tool is a plain
function, and there is nowhere else for a dependency to live.
"""

from code_reviewer.application.ports import CodeRetriever
from code_reviewer.domain.retrieval import render_chunks

from .output import truncate

_retriever: CodeRetriever | None = None


def set_retriever(retriever: CodeRetriever | None) -> None:
    """Sets the index `search_related_code` searches.

    ``None`` — the default — makes the tool say so rather than pretending the
    repository is empty. A model told "there is no index" can reach for grep; a
    model told "no results" concludes the code is unique.
    """
    global _retriever
    _retriever = retriever


def get_retriever() -> CodeRetriever | None:
    """The active retriever, or ``None`` when this run has no index."""
    return _retriever


class RetrievalTools:
    #: Most chunks one call may return. Four citations is a paragraph of
    #: context; twenty is the diff pushed out of the window by its own
    #: background reading.
    MAX_RESULTS = 4

    @staticmethod
    def search_related_code(query: str) -> str:
        """Searches the indexed repository for code related to ``query``."""
        retriever = get_retriever()
        if retriever is None:
            return (
                "No repository index is available in this run. Use grep_search or "
                "find_file instead; do not conclude that nothing similar exists."
            )

        try:
            chunks = retriever.related(query, limit=RetrievalTools.MAX_RESULTS)
        except Exception as exc:
            return f"Error searching the repository index: {exc}"

        if not chunks:
            return f"No indexed code matched '{query}'."

        return truncate(render_chunks(chunks))
