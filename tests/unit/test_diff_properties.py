"""Input nobody wrote by hand.

Triage and the semantic analyzer read diffs, and a diff is written by whoever
opened the merge request. Every case they were tested against until now was
imagined by someone, and malformed input is free to produce (finding G-17).

"Never raises" is a weak property, which is exactly what makes it the right
one here: cheap to state, cheap to check, and a violation is always a real
bug. An exception in either component costs the file its whole review — and
since Level 9 an analysis that could not run blocks the pipeline, so a crash
on a malformed diff is a merge request nobody can land.
"""

import unittest

import pytest

pytest.importorskip("hypothesis", reason="hypothesis is not installed")

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.suppression import parse_directives
from code_reviewer.domain.triage import ReviewDecision, ReviewTriage
from code_reviewer.infrastructure.analyzers.semantic import SemanticChangeAnalyzer

TRIAGE = ReviewTriage(ReviewPolicy())
SEMANTIC = SemanticChangeAnalyzer()

#: Deadlines off: the first example pays for compiling every policy regex, and
#: a property that times out is a configuration mistake rather than a bug.
SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

#: Lines that look like the parts of a unified diff, plus arbitrary text.
diff_lines = st.lists(
    st.one_of(
        st.text(max_size=60).map(lambda s: "+" + s),
        st.text(max_size=60).map(lambda s: "-" + s),
        st.text(max_size=60).map(lambda s: " " + s),
        st.text(max_size=60),
        st.just("+++ b/file.py"),
        st.just("--- a/file.py"),
        st.just("@@ -1,3 +1,4 @@"),
        st.just("\\ No newline at end of file"),
    ),
    max_size=40,
)

paths = st.one_of(
    st.just(""),
    st.text(max_size=40),
    st.sampled_from(["src/app.py", "a.c", "Dockerfile", ".github/workflows/ci.yml", "x.md"]),
)


class TestTriageSurvivesAnything(unittest.TestCase):
    @SETTINGS
    @given(lines=diff_lines)
    def test_a_decision_comes_back_for_any_diff(self, lines):
        result = TRIAGE.decide("\n".join(lines), "src/app.py")

        self.assertIsInstance(result.decision, ReviewDecision)

    @SETTINGS
    @given(path=paths)
    def test_a_decision_comes_back_for_any_path(self, path):
        result = TRIAGE.decide("+ added\n", path)

        self.assertIsInstance(result.decision, ReviewDecision)

    @SETTINGS
    @given(diff=st.text(max_size=400), path=paths)
    def test_arbitrary_text_is_not_an_exception(self, diff, path):
        self.assertIsInstance(TRIAGE.decide(diff, path).decision, ReviewDecision)

    @SETTINGS
    @given(lines=diff_lines, content=st.text(max_size=400))
    def test_full_content_does_not_change_that(self, lines, content):
        result = TRIAGE.decide("\n".join(lines), "src/app.py", content)

        self.assertIsInstance(result.decision, ReviewDecision)


class TestTheSemanticAnalyzerSurvivesAnything(unittest.TestCase):
    @SETTINGS
    @given(lines=diff_lines)
    def test_an_analysis_comes_back_for_any_diff(self, lines):
        analysis = SEMANTIC.analyze_diff("\n".join(lines), None, "src/app.py")

        self.assertIsNotNone(analysis.change_type)

    @SETTINGS
    @given(lines=diff_lines, content=st.text(max_size=400))
    def test_unparseable_content_is_not_an_exception(self, lines, content):
        analysis = SEMANTIC.analyze_diff("\n".join(lines), content, "src/app.py")

        self.assertIsNotNone(analysis.change_type)

    @SETTINGS
    @given(diff=st.text(max_size=400))
    def test_arbitrary_text_is_not_an_exception(self, diff):
        self.assertIsNotNone(SEMANTIC.analyze_diff(diff, None, "m.py").change_type)


class TestTheSuppressionParserSurvivesAnything(unittest.TestCase):
    """It reads source files, which are as untrusted as the diff."""

    @SETTINGS
    @given(source=st.text(max_size=400))
    def test_arbitrary_source_yields_a_list(self, source):
        self.assertIsInstance(parse_directives(source), list)

    @SETTINGS
    @given(rule=st.text(max_size=30), reason=st.text(max_size=40))
    def test_a_directive_built_from_arbitrary_text_does_not_raise(self, rule, reason):
        source = f"x = 1  # review-ignore: {rule} - {reason}\n"

        self.assertIsInstance(parse_directives(source), list)


if __name__ == "__main__":
    unittest.main()
