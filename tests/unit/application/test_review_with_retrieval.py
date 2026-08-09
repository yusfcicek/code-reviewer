"""Step 11 — retrieval reaching the reviewer, and failing without cost."""

import unittest

from code_reviewer.application.ports import CodeForge, CodeRetriever, FileChange, MergeRequestRef, Reviewer
from code_reviewer.application.retrieval_service import query_from_change
from code_reviewer.application.review_service import ReviewService
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.retrieval import CodeChunk
from code_reviewer.domain.triage import ReviewTriage

DIFF = "\n".join(
    [
        "@@ -1,4 +1,12 @@",
        "+def authenticate_user(token):",
        "+    if not token:",
        "+        raise ValueError('no token')",
        "+    return verify_token(token)",
        "-def old_thing():",
        "-    pass",
    ]
)

CHUNK = CodeChunk(
    path="auth/session.py",
    start_line=10,
    end_line=14,
    text="def verify_token(token):\n    return decode(token)",
    name="verify_token",
)


class RecordingReviewer(Reviewer):
    def __init__(self):
        self.related_seen: list | None = None

    def review_diff(self, brief):
        self.related_seen = list(brief.related)
        return "## Review\nLooks fine."


class FakeForge(CodeForge):
    def __init__(self, changes):
        self._changes = changes
        self.published: list[str] = []

    def fetch_merge_request(self, project_id, merge_request_iid):
        return MergeRequestRef(project_id=str(project_id), merge_request_id=str(merge_request_iid))

    def fetch_changes(self, reference):
        return list(self._changes)

    def fetch_file(self, reference, path):
        return "def authenticate_user(token):\n    return verify_token(token)\n"

    def publish_comment(self, reference, body):
        self.published.append(body)


class StubRetriever(CodeRetriever):
    def __init__(self, chunks=(), error=None):
        self._chunks = list(chunks)
        self._error = error
        self.calls: list[tuple[str, int, str]] = []

    def related(self, query, limit=5, exclude_path=""):
        self.calls.append((query, limit, exclude_path))
        if self._error is not None:
            raise self._error
        return list(self._chunks)


def _service(forge, reviewer, retriever=None) -> ReviewService:
    return ReviewService(
        forge=forge,
        reviewer=reviewer,
        triage=ReviewTriage(ReviewPolicy()),
        policy=ReviewPolicy(),
        retriever=retriever,
        clock=lambda: 0,
    )


class TestRetrievalReachesTheReviewer(unittest.TestCase):
    def test_retrieved_chunks_are_passed_to_the_reviewer(self):
        reviewer = RecordingReviewer()
        forge = FakeForge([FileChange("auth/tokens.py", DIFF)])

        _service(forge, reviewer, StubRetriever([CHUNK])).review(1, 2, publish=False)

        self.assertEqual(reviewer.related_seen, [CHUNK])

    def test_the_file_under_review_is_excluded_from_its_own_context(self):
        retriever = StubRetriever([CHUNK])
        forge = FakeForge([FileChange("auth/tokens.py", DIFF)])

        _service(forge, RecordingReviewer(), retriever).review(1, 2, publish=False)

        self.assertEqual(retriever.calls[0][2], "auth/tokens.py")

    def test_the_query_is_built_from_the_change(self):
        retriever = StubRetriever([CHUNK])
        forge = FakeForge([FileChange("auth/tokens.py", DIFF)])

        _service(forge, RecordingReviewer(), retriever).review(1, 2, publish=False)

        query = retriever.calls[0][0]
        self.assertIn("authenticate_user", query)
        self.assertIn("tokens", query)

    def test_without_a_retriever_the_reviewer_is_given_nothing(self):
        reviewer = RecordingReviewer()
        forge = FakeForge([FileChange("auth/tokens.py", DIFF)])

        _service(forge, reviewer).review(1, 2, publish=False)

        self.assertEqual(reviewer.related_seen, [])


class TestRetrievalFailsWithoutCost(unittest.TestCase):
    def test_a_retriever_that_raises_leaves_the_review_intact(self):
        """Level 9 made a failed *analysis* block, because a gate must not
        read "nothing examined" as "nothing found". A failed *retrieval* has
        no such property: the prompt is smaller, and that is all."""
        reviewer = RecordingReviewer()
        forge = FakeForge([FileChange("auth/tokens.py", DIFF)])

        result = _service(forge, reviewer, StubRetriever(error=RuntimeError("index gone"))).review(
            1, 2, publish=False
        )

        self.assertEqual(reviewer.related_seen, [])
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.outcome.failed_files)
        self.assertFalse(result.outcome.unanalysed_files)

    def test_a_retrieval_failure_produces_no_finding(self):
        forge = FakeForge([FileChange("auth/tokens.py", DIFF)])

        result = _service(forge, RecordingReviewer(), StubRetriever(error=RuntimeError("index gone"))).review(
            1, 2, publish=False
        )

        self.assertEqual([finding.rule_id for finding in result.findings], [])

    def test_the_failure_is_logged(self):
        forge = FakeForge([FileChange("auth/tokens.py", DIFF)])

        with self.assertLogs("code_reviewer.application.review_service", level="WARNING") as captured:
            _service(forge, RecordingReviewer(), StubRetriever(error=RuntimeError("index gone"))).review(
                1, 2, publish=False
            )

        self.assertTrue(any("Retrieval failed" in line for line in captured.output))


class TestQueryConstruction(unittest.TestCase):
    def test_added_lines_and_the_file_name_make_the_query(self):
        query = query_from_change("auth/tokens.py", DIFF)

        self.assertIn("authenticate_user", query)
        self.assertIn("tokens", query)

    def test_removed_lines_are_not_in_the_query(self):
        """Retrieval is looking for code like the *new* code."""
        self.assertNotIn("old_thing", query_from_change("auth/tokens.py", DIFF))

    def test_hunk_headers_are_not_in_the_query(self):
        self.assertNotIn("@@", query_from_change("auth/tokens.py", DIFF))

    def test_the_file_header_is_not_mistaken_for_an_added_line(self):
        query = query_from_change("a.py", "+++ b/a.py\n+value = 1\n")

        self.assertNotIn("+ b/a.py", query)
        self.assertIn("value = 1", query)

    def test_a_query_is_bounded(self):
        huge = "\n".join(f"+line_{index} = {index}" for index in range(5000))

        self.assertLessEqual(len(query_from_change("a.py", huge)), 2100)

    def test_a_diff_with_no_additions_still_names_the_file(self):
        self.assertIn("tokens", query_from_change("auth/tokens.py", "-def gone(): pass\n"))


if __name__ == "__main__":
    unittest.main()
