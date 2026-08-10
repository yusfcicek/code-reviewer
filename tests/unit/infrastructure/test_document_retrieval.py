"""Self-review finding S-01 — the tier that returned nothing.

Documents and code shared one index, and the retrieval limit was applied by the
retriever *before* the service filtered for documents. Code won every ranking,
so the three chunks that came back were always code and were always discarded.
Measured against the real corpus: 0 documents in the top 20.

Every Tier B test passed, because each one handed the service a document chunk
directly. A fake that returns what it was given cannot fail this way. So these
tests build the real retriever over real content, which is the only
configuration the tier ever runs in.
"""

from code_reviewer.infrastructure.retrieval.document_corpus import build_document_retriever

CODE = '''
def apply_suppressions(findings, directives, policy):
    """Applies directives to findings."""
    return [finding for finding in findings if finding not in directives]


class SuppressionResult:
    def __init__(self, findings, suppressed):
        self.findings = findings
        self.suppressed = suppressed
'''

GUIDE = """# Guide

## Silencing a rule

A directive silences one rule on one line, and the written reason is what the
next person reads instead of re-deriving the judgement.

## Retrieval

Chunks are scored twice and fused by rank.
"""

DIFF = (
    "@@ -1,4 +1,4 @@\n"
    "-def apply_suppressions(findings, directives):\n"
    "+def apply_suppressions(findings, directives, policy):\n"
    "     return findings\n"
)


def _tree(tmp_path):
    (tmp_path / "app.py").write_text(CODE)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(GUIDE)
    return tmp_path


def test_a_document_survives_the_limit_even_beside_code(tmp_path):
    """The measurement that failed: 0 of 3, every time."""
    retriever = build_document_retriever(_tree(tmp_path))

    returned = retriever.related(DIFF, limit=3)

    assert returned, "the tier retrieved nothing at all"
    assert all(chunk.path.endswith(".md") for chunk in returned), [c.path for c in returned]


def test_the_retriever_holds_only_documents(tmp_path):
    """Not a filter applied afterwards — code is never in this index, so it
    cannot consume the limit before the filter runs."""
    retriever = build_document_retriever(_tree(tmp_path))

    assert all(chunk.path.endswith(".md") for chunk in retriever.related("apply suppressions", limit=20))


def test_sections_are_retrieved_rather_than_whole_documents(tmp_path):
    returned = build_document_retriever(_tree(tmp_path)).related(DIFF, limit=1)

    assert returned[0].name in ("Silencing a rule", "Retrieval", "Guide")


def test_a_tree_with_no_documents_yields_a_retriever_that_answers_nothing(tmp_path):
    (tmp_path / "app.py").write_text(CODE)

    assert build_document_retriever(tmp_path).related(DIFF, limit=3) == []


def test_a_missing_directory_yields_a_retriever_rather_than_an_error(tmp_path):
    assert build_document_retriever(tmp_path / "absent").related(DIFF, limit=3) == []
