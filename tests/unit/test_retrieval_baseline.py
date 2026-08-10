"""Steps 3 and 4 — the measurement Level 23 said did not exist.

Level 23 refused to measure the retrieved tier because its answer comes from a
model. That is true of the *judgement*, and it was taken to be true of the whole
tier — which is how the tier came to return nothing at all for a level with
nothing to notice.

The half that is deterministic: given a change and a set of documents, does the
section a reader says relates to it come back, and at what rank? No model, no
recording, no author's opinion about correctness.
"""

import pytest

from code_reviewer.application.retrieval_recall import (
    RecallCase,
    measure_recall,
    render_recall_report,
)
from code_reviewer.application.retrieval_service import HybridRetriever
from code_reviewer.infrastructure.evaluation.retrieval_dataset import (
    RetrievalCorpus,
    RetrievalDatasetError,
)
from code_reviewer.infrastructure.retrieval.chunking import chunk_markdown
from code_reviewer.infrastructure.retrieval.embedding import HashingEmbedding
from code_reviewer.infrastructure.retrieval.lexical import BM25Index
from code_reviewer.infrastructure.retrieval.vector_index import InMemoryVectorIndex

#: The floor committed to CI, on the interval's lower bound (Level 25's rule).
#: Five cases at 1.00 support 0.57, so the floor is 0.55 — what the corpus
#: carries and not a decimal more. A later level that writes cases earns more.
MIN_RECALL = 0.55

#: How deep the measurement looks. The tier's own per-file limit, because
#: measuring at a depth the tier never uses measures something else.
LIMIT = 3


def _build(documents):
    retriever = HybridRetriever(
        embedding=HashingEmbedding(), lexical=BM25Index(), vectors=InMemoryVectorIndex()
    )
    retriever.index([chunk for path, text in documents for chunk in chunk_markdown(path, text)])
    return retriever


@pytest.fixture(scope="module")
def cases():
    return RetrievalCorpus("evaluation").cases()


@pytest.fixture(scope="module")
def report(cases):
    return measure_recall(cases, _build, limit=LIMIT)


class TestTheCorpus:
    def test_it_loads(self, cases):
        assert len(cases) >= 5

    def test_every_case_carries_the_document_it_expects(self, cases):
        for case in cases:
            assert any(path == case.path for path, _ in case.documents), case.name

    def test_every_case_says_why_a_human_thinks_they_relate(self, cases):
        """The case is only fair if somebody can read the argument and disagree."""
        for case in cases:
            assert case.because.strip(), case.name

    def test_no_case_names_its_section_in_the_diff(self, cases):
        """The reason the tier exists. A change whose diff contains the
        section's own heading would be found by a token match, and would
        measure the wrong thing."""
        for case in cases:
            assert case.heading.lower() not in case.diff.lower(), case.name

    def test_a_missing_corpus_is_refused_rather_than_scored_as_empty(self):
        with pytest.raises(RetrievalDatasetError):
            RetrievalCorpus("evaluation/nothing-here").cases()


class TestTheMeasurement:
    def test_no_case_was_broken(self, report):
        assert report.errors == ()

    def test_it_holds_the_committed_floor(self, report):
        assert report.interval.lower >= MIN_RECALL

    def test_the_interval_is_over_cases(self, report, cases):
        assert report.interval.total == len(cases)

    def test_the_rank_is_recorded_not_just_the_hit(self, report):
        """AC-8. 'In the top three' and 'first' are different facts about a
        tier whose per-file limit is three."""
        assert all(result.rank > 0 for result in report.results)

    def test_a_case_that_misses_is_named(self):
        """AC-9. Averaged away, a miss is invisible."""
        case = RecallCase(
            name="impossible",
            diff="@@ -1,1 +1,1 @@\n+x = 1\n",
            path="docs/a.md",
            heading="Nowhere",
            documents=(("docs/a.md", "# A\n\n## Something else\n\nBody.\n"),),
            because="deliberately unfindable",
        )

        assert measure_recall([case], _build, limit=3).missed == ("impossible",)

    def test_a_case_naming_a_document_it_does_not_carry_is_an_error_not_a_miss(self):
        case = RecallCase(
            name="broken",
            diff="x",
            path="docs/absent.md",
            heading="H",
            documents=(("docs/a.md", "# A\n\nb\n"),),
        )

        report = measure_recall([case], _build, limit=3)

        assert report.errors == ("broken",)
        assert report.results == ()

    def test_an_empty_corpus_measures_nothing_rather_than_scoring_one(self):
        """The defect Level 25 found in the analyzer harness, not repeated."""
        report = measure_recall([], _build, limit=3)

        assert report.interval.lower == 0.0


class TestTheReport:
    def test_it_states_the_interval_and_the_limit(self, report):
        text = render_recall_report(report, MIN_RECALL)

        assert "over 5" in text
        assert "top 3" in text

    def test_it_states_how_often_the_section_came_first(self, report):
        assert "First place" in render_recall_report(report, MIN_RECALL)

    def test_it_says_what_is_not_measured(self, report):
        """The sentence that keeps this from being read as a quality score."""
        assert "whether the model was right" in render_recall_report(report, MIN_RECALL)

    def test_a_miss_is_listed(self):
        case = RecallCase(
            name="impossible",
            diff="+x = 1\n",
            path="docs/a.md",
            heading="Nowhere",
            documents=(("docs/a.md", "# A\n\n## Something else\n\nBody.\n"),),
        )

        text = render_recall_report(measure_recall([case], _build, limit=3), MIN_RECALL)

        assert "1 case(s) missed" in text
