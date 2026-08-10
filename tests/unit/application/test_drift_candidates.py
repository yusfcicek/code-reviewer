"""Step 7 — the tier that finds what no token match reaches.

Its value and its danger are the same property: it can relate a change to a
paragraph that names nothing. So every test here is about a bound — what it
never asks about, how many it asks about, and what happens when the machinery
underneath it fails.
"""

from code_reviewer.application.drift_service import DriftService
from code_reviewer.application.ports import FileChange
from code_reviewer.domain.drift import DriftCandidate, DriftVerdict
from code_reviewer.domain.retrieval import CodeChunk
from code_reviewer.domain.severity import Severity

SECTION = "## Suppression\n\nA directive silences a rule, and the reason is what the next person reads.\n"


class _Retriever:
    """Returns what it was given, and remembers what it was asked."""

    def __init__(self, chunks=None, error=None):
        self._chunks = chunks or []
        self._error = error
        self.queries = []

    def related(self, query, limit=5, exclude_path=""):
        self.queries.append((query, limit))
        if self._error is not None:
            raise self._error
        return list(self._chunks)[:limit]

    def index(self, chunks):  # pragma: no cover - not exercised here
        raise NotImplementedError


class _Judge:
    def __init__(self, verdict=DriftVerdict.STALE, error=None):
        self._verdict = verdict
        self._error = error
        self.asked = []

    def still_describes(self, candidate):
        self.asked.append(candidate)
        if self._error is not None:
            raise self._error
        return self._verdict


def _chunk(path="docs/guide.md", line=5, name="Suppression", text=SECTION):
    return CodeChunk(path=path, start_line=line, end_line=line + 3, text=text, name=name)


def _change(path="code_reviewer/domain/suppression.py", diff="@@ -1,1 +1,1 @@\n-old\n+new\n"):
    return FileChange(path=path, diff=diff)


class TestWhatBecomesACandidate:
    def test_a_retrieved_section_the_model_calls_stale_becomes_a_finding(self):
        outcome = DriftService(_Retriever([_chunk()]), _Judge()).review([_change()])

        assert [finding.rule_id for finding in outcome.findings] == ["DRIFT.POSSIBLE_STALE_SECTION"]

    def test_a_section_the_model_calls_current_produces_nothing(self):
        outcome = DriftService(_Retriever([_chunk()]), _Judge(DriftVerdict.CURRENT)).review([_change()])

        assert outcome.findings == []

    def test_an_unsure_answer_produces_nothing(self):
        """A candidate list padded with maybes is a list nobody finishes."""
        outcome = DriftService(_Retriever([_chunk()]), _Judge(DriftVerdict.UNSURE)).review([_change()])

        assert outcome.findings == []

    def test_a_retrieved_source_file_is_not_a_candidate(self):
        """The corpus holds code too. This tier is about documents."""
        judge = _Judge()

        DriftService(_Retriever([_chunk(path="app.py", name="create_app")]), judge).review([_change()])

        assert judge.asked == []

    def test_a_document_the_change_already_edited_is_not_a_candidate(self):
        """C-6 — updating the README in the same merge request is the
        behaviour this level wants, and reporting it trains people out of it."""
        judge = _Judge()

        DriftService(_Retriever([_chunk()]), judge).review([_change()], {"docs/guide.md": "..."})

        assert judge.asked == []

    def test_a_changed_document_is_not_itself_a_query(self):
        retriever = _Retriever([_chunk()])

        DriftService(retriever, _Judge()).review([_change(path="README.md")])

        assert retriever.queries == []

    def test_a_change_with_no_diff_is_not_a_query(self):
        retriever = _Retriever([_chunk()])

        DriftService(retriever, _Judge()).review([_change(diff="")])

        assert retriever.queries == []

    def test_one_section_is_asked_about_once_however_many_files_point_at_it(self):
        judge = _Judge()
        changes = [_change(path="a.py"), _change(path="b.py")]

        DriftService(_Retriever([_chunk()]), judge).review(changes)

        assert len(judge.asked) == 1


class TestBounds:
    def test_the_per_file_limit_reaches_the_retriever(self):
        retriever = _Retriever([_chunk()])

        DriftService(retriever, _Judge(), per_file=2).review([_change()])

        assert retriever.queries[0][1] == 2

    def test_the_cap_bounds_how_many_reach_the_model(self):
        chunks = [_chunk(line=line, name=f"S{line}") for line in range(1, 20, 4)]
        judge = _Judge()

        DriftService(_Retriever(chunks), judge, per_file=10, cap=2).review([_change()])

        assert len(judge.asked) == 2

    def test_the_cap_says_what_it_dropped(self):
        """AC-16 — a truncation nobody can see reads as coverage."""
        chunks = [_chunk(line=line, name=f"S{line}") for line in range(1, 20, 4)]

        outcome = DriftService(_Retriever(chunks), _Judge(), per_file=10, cap=2).review([_change()])

        assert outcome.dropped == 3

    def test_nothing_dropped_is_reported_as_nothing(self):
        outcome = DriftService(_Retriever([_chunk()]), _Judge()).review([_change()])

        assert outcome.dropped == 0


class TestFailure:
    def test_a_retriever_that_raises_costs_the_tier_and_nothing_else(self):
        outcome = DriftService(_Retriever(error=RuntimeError("no index")), _Judge()).review([_change()])

        assert outcome.findings == []
        assert "retrieval" in outcome.degraded.lower()

    def test_a_judge_that_raises_costs_its_candidate_only(self):
        chunks = [_chunk(line=1, name="A"), _chunk(line=9, name="B")]
        judge = _Judge(error=RuntimeError("model down"))

        outcome = DriftService(_Retriever(chunks), judge).review([_change()])

        assert outcome.findings == []
        assert len(judge.asked) == 2
        assert outcome.degraded == ""

    def test_a_run_with_no_changes_asks_nothing(self):
        judge = _Judge()

        assert DriftService(_Retriever([_chunk()]), judge).review([]).findings == []
        assert judge.asked == []


class TestWhatTheFindingSays:
    def _finding(self):
        return DriftService(_Retriever([_chunk()]), _Judge()).review([_change()]).findings[0]

    def test_it_points_at_the_document_and_the_section(self):
        finding = self._finding()

        assert finding.file_path == "docs/guide.md"
        assert finding.line_number == 5
        assert "Suppression" in finding.description

    def test_it_names_the_change_that_raised_it(self):
        assert "suppression.py" in self._finding().description

    def test_it_says_it_is_unverified(self):
        """AC-17's half that lives in the finding rather than the renderer."""
        assert "unverified" in self._finding().description.lower()

    def test_it_never_carries_the_section_text(self):
        """AC-14 — the model read the prose; the report names its location."""
        finding = self._finding()

        for field in (finding.title, finding.description, finding.remediation, finding.evidence):
            assert "the next person reads" not in field

    def test_it_is_the_lowest_severity_there_is(self):
        assert self._finding().severity is Severity.INFO


class TestTheVerdictType:
    def test_a_bare_word_parses(self):
        assert DriftVerdict.parse("stale") is DriftVerdict.STALE

    def test_capitalisation_and_punctuation_are_tolerated(self):
        for answer in ("Stale.", "  STALE  ", "**stale**", "stale — the section is old"):
            assert DriftVerdict.parse(answer) is DriftVerdict.STALE, answer

    def test_current_parses(self):
        assert DriftVerdict.parse("current") is DriftVerdict.CURRENT

    def test_anything_unreadable_is_unsure(self):
        for answer in ("", "   ", "I think perhaps", "yes", "42"):
            assert DriftVerdict.parse(answer) is DriftVerdict.UNSURE, answer

    def test_only_a_positive_answer_is_reportable(self):
        assert DriftVerdict.STALE.is_reportable
        assert not DriftVerdict.CURRENT.is_reportable
        assert not DriftVerdict.UNSURE.is_reportable


def test_a_candidate_carries_its_location_and_its_text():
    candidate = DriftCandidate(
        path="docs/guide.md", line=5, heading="Suppression", text=SECTION, source_path="a.py"
    )

    assert candidate.path == "docs/guide.md"
    assert candidate.text == SECTION
