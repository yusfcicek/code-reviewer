"""Step 6 — Tier A, wired to a merge request.

Both directions of C-1 meet here: the code changed, so the documents that named
what it removed are checked; the documents changed, so what they now claim is
checked against the tree.

Everything this tier reports is at `Severity.LOW` and none of it reaches
`blocking_issues`. That is not modesty — the rules are unmeasured, and this
repository earns a floor by measuring one (Level 12, D-4).
"""

from code_reviewer.application.documentation_service import DocumentationService
from code_reviewer.application.ports import FileChange
from code_reviewer.domain.documentation import SymbolIndex
from code_reviewer.domain.finding import FindingCategory
from code_reviewer.domain.severity import Severity

INDEX = SymbolIndex(
    names=frozenset({"create_app", "Renderer", "Renderer.render"}),
    signatures={"create_app": ("config",), "Renderer.render": ("version",)},
    options=frozenset({"--strict"}),
    environment=frozenset({"CI_PROJECT_ID"}),
)

REMOVED_START_APP = "@@ -1,4 +1,1 @@\n-def start_app(config):\n-    return config\n def create_app(config):\n"

DOCUMENTS = [
    ("README.md", "# Guide\n\nBoot with `start_app`, then `create_app`.\n"),
    ("docs/other.md", "# Other\n\nNothing to do with any of this.\n"),
]


def _service(index=INDEX, documents=None):
    return DocumentationService(index=index, documents=documents if documents is not None else DOCUMENTS)


def _change(path="app.py", diff=REMOVED_START_APP):
    return FileChange(path=path, diff=diff)


class TestTheCodeChangedDirection:
    def test_a_document_naming_a_removed_symbol_is_reported(self):
        outcome = _service().review([_change()], {"app.py": ""})

        assert [finding.rule_id for finding in outcome.findings] == ["DOCS.DEAD_REFERENCE"]

    def test_the_finding_points_at_the_document_rather_than_the_code(self):
        finding = _service().review([_change()], {"app.py": ""}).findings[0]

        assert finding.file_path == "README.md"
        assert finding.line_number == 3

    def test_a_document_about_something_else_is_not_reported(self):
        outcome = _service().review([_change()], {"app.py": ""})

        assert all(finding.file_path != "docs/other.md" for finding in outcome.findings)

    def test_a_change_that_removed_nothing_reports_nothing(self):
        change = _change(diff="@@ -1,1 +1,2 @@\n def create_app(config):\n+    pass\n")

        assert _service().review([change], {"app.py": ""}).findings == []


class TestTheDocumentChangedDirection:
    def test_an_edited_document_has_its_signatures_checked(self):
        documents = [("README.md", "Call `create_app(config, worker)`.\n")]
        change = _change(path="README.md", diff="@@ -1,1 +1,1 @@\n+Call `create_app(config, worker)`.\n")

        outcome = _service(documents=documents).review([change], {})

        assert [finding.rule_id for finding in outcome.findings] == ["DOCS.SIGNATURE_MISMATCH"]

    def test_an_unedited_document_with_the_same_claim_is_not_checked(self):
        documents = [("README.md", "Call `create_app(config, worker)`.\n")]

        assert _service(documents=documents).review([_change()], {"app.py": ""}).findings == []


class TestDocstrings:
    SOURCE = '''
def render(version):
    """Renders.

    Args:
        version: the policy version.
        outcome: gone.
    """
    return version
'''

    def test_a_changed_source_file_is_checked_for_docstring_drift(self):
        outcome = _service().review(
            [_change(path="render.py", diff="@@ -1,1 +1,1 @@\n+x = 1\n")], {"render.py": self.SOURCE}
        )

        assert [finding.rule_id for finding in outcome.findings] == ["DOCS.DOCSTRING_DRIFT"]

    def test_the_finding_names_the_source_file_and_the_function_line(self):
        finding = (
            _service().review([_change(path="render.py", diff="")], {"render.py": self.SOURCE}).findings[0]
        )

        assert finding.file_path == "render.py"
        assert finding.line_number == 2

    def test_a_source_file_that_did_not_change_is_not_checked(self):
        outcome = _service().review([], {"render.py": self.SOURCE})

        assert outcome.findings == []

    def test_a_file_that_is_not_python_is_not_parsed_as_python(self):
        outcome = _service().review([_change(path="notes.txt", diff="")], {"notes.txt": self.SOURCE})

        assert outcome.findings == []


class TestWhatItRefusesToDo:
    def test_every_finding_is_low_severity(self):
        """AC-13. Nothing this level produces is allowed to block, and the
        cheapest way to keep that true is to never emit anything that could."""
        outcome = _service().review([_change()], {"app.py": ""})

        assert all(finding.severity is Severity.LOW for finding in outcome.findings)

    def test_every_finding_is_categorised_as_documentation(self):
        outcome = _service().review([_change()], {"app.py": ""})

        assert all(finding.category is FindingCategory.DOCUMENTATION for finding in outcome.findings)

    def test_no_finding_carries_a_sentence_from_the_document(self):
        """AC-14 — identifiers only, and the identifiers are the point."""
        documents = [("README.md", "# Guide\n\nThe boot path is delicate, so `start_app` runs last.\n")]

        outcome = _service(documents=documents).review([_change()], {"app.py": ""})

        for finding in outcome.findings:
            for field in (finding.title, finding.description, finding.remediation, finding.evidence):
                assert "delicate" not in field

    def test_every_finding_names_its_rule(self):
        """Level 20 refuses to attribute a finding with an empty rule id."""
        outcome = _service().review([_change()], {"app.py": ""})

        assert all(finding.rule_id.startswith("DOCS.") for finding in outcome.findings)


class TestDegradation:
    def test_an_index_that_did_not_build_reports_nothing(self):
        outcome = _service(index=SymbolIndex.EMPTY).review([_change()], {"app.py": ""})

        assert outcome.findings == []

    def test_an_index_that_did_not_build_says_so(self):
        """C-2 — an analyzer that could not run is recorded rather than silent
        (the pattern self-review 12–20 S-02 established)."""
        outcome = _service(index=SymbolIndex.EMPTY).review([_change()], {"app.py": ""})

        assert outcome.degraded
        assert "index" in outcome.degraded.lower()

    def test_a_working_index_records_no_degradation(self):
        assert _service().review([_change()], {"app.py": ""}).degraded == ""

    def test_a_document_that_cannot_be_read_costs_that_document_only(self):
        documents = [("bad.md", None), ("README.md", DOCUMENTS[0][1])]

        outcome = _service(documents=documents).review([_change()], {"app.py": ""})

        assert [finding.file_path for finding in outcome.findings] == ["README.md"]

    def test_nothing_raises_on_an_empty_review(self):
        assert _service(documents=[]).review([], {}).findings == []
