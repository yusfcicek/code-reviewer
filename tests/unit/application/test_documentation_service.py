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


class TestAttribution:
    """AC-12 — the split that makes the safety argument a table lookup."""

    def test_the_resolved_namespace_is_deterministic(self):
        from code_reviewer.application.governance import producer_for
        from code_reviewer.domain.provenance import ProducerKind

        assert producer_for("DOCS.DEAD_REFERENCE", "2.17.0").kind is ProducerKind.ANALYZER

    def test_the_retrieved_namespace_is_an_agent(self):
        from code_reviewer.application.governance import producer_for
        from code_reviewer.domain.provenance import ProducerKind

        assert producer_for("DRIFT.POSSIBLE_STALE_SECTION", "2.17.0").kind is ProducerKind.AGENT

    def test_a_blocking_verdict_citing_a_retrieved_finding_cannot_be_built(self):
        """Level 20's refusal, asserted against the new namespace. Nothing in
        this level had to implement it — the table did."""
        import pytest

        from code_reviewer.application.governance import provenance_of
        from code_reviewer.domain.finding import Finding
        from code_reviewer.domain.provenance import DecisionRecord, RunIdentity

        drift = Finding(
            category=FindingCategory.DOCUMENTATION,
            severity=Severity.INFO,
            file_path="docs/guide.md",
            line_number=5,
            title="A documentation section may no longer describe this change",
            description="",
            remediation="",
            rule_id="DRIFT.POSSIBLE_STALE_SECTION",
        )
        claims = (provenance_of(drift, "2.17.0"),)

        with pytest.raises(ValueError):
            DecisionRecord(
                verdict="fail",
                exit_code=1,
                identity=RunIdentity(package_version="2.17.0", policy_version="1.0"),
                findings=claims,
                blocking=claims,
            )


class TestNothingHereBlocks:
    """AC-13, asserted against the real gate rather than against a constant."""

    def _outcome_with_documentation_findings(self):
        from code_reviewer.domain.gate import ReviewGate
        from code_reviewer.domain.outcome import ReviewOutcome
        from code_reviewer.domain.policy import ReviewPolicy

        findings = _service().review([_change()], {"app.py": ""}).findings
        assert findings, "the fixture must produce something for this to test anything"

        outcome = ReviewOutcome()
        outcome.record("app.py", ReviewGate(ReviewPolicy()).evaluate("", findings))
        return outcome

    def test_no_documentation_finding_reaches_the_blocking_list(self):
        outcome = self._outcome_with_documentation_findings()

        assert outcome.blocking_issues == []

    def test_a_review_of_nothing_but_documentation_findings_passes(self):
        assert not self._outcome_with_documentation_findings().is_blocking


class TestADeletedFile:
    """Self-review S-03 — the most obvious stale reference, missed.

    `ReviewService` filtered `is_deleted` changes out before anything saw them,
    which is right for reviewing (there is nothing left to review) and wrong
    for this: deleting the module a document describes is the plainest way to
    make the document stale, and it produced nothing at all.

    The forge does carry the deletion's diff — every line as a removal — so the
    names are available from the same subtraction every other change uses. The
    defect was only that the change never arrived.
    """

    DELETION = (
        "@@ -1,6 +0,0 @@\n"
        "-def start_app(config):\n"
        '-    """Boots it."""\n'
        "-    return config\n"
        "-\n"
        "-\n"
        "-class LegacyRenderer:\n"
    )

    def _outcome(self, diff=None, documents=None):
        deleted = FileChange(path="legacy.py", diff=self.DELETION if diff is None else diff, is_deleted=True)
        documents = (
            documents
            if documents is not None
            else [("README.md", "# Guide\n\nBoot with `start_app`, then `create_app`.\n")]
        )
        return DocumentationService(index=INDEX, documents=documents).review([deleted], {})

    def test_a_symbol_the_deleted_file_defined_is_reported(self):
        assert [finding.rule_id for finding in self._outcome().findings] == ["DOCS.DEAD_REFERENCE"]

    def test_the_finding_points_at_the_document(self):
        finding = self._outcome().findings[0]

        assert finding.file_path == "README.md"
        assert finding.line_number == 3

    def test_a_deletion_with_no_diff_reports_nothing(self):
        """No diff, no names, no guess."""
        assert self._outcome(diff="").findings == []

    def test_a_symbol_that_still_exists_elsewhere_is_not_reported(self):
        """Moving a module is not deleting a function."""
        documents = [("README.md", "Boot with `create_app`.\n")]
        diff = "@@ -1,2 +0,0 @@\n-def create_app(config, worker):\n-    return config\n"

        assert self._outcome(diff=diff, documents=documents).findings == []

    def test_a_deleted_file_is_not_checked_for_docstring_drift(self):
        """Its docstrings are gone. Reporting them is reporting nothing."""
        source = 'def gone(a):\n    """X.\n\n    Args:\n        b: absent.\n    """\n'
        deleted = FileChange(path="legacy.py", diff=self.DELETION, is_deleted=True)

        outcome = DocumentationService(index=INDEX, documents=[]).review([deleted], {"legacy.py": source})

        assert all(finding.rule_id != "DOCS.DOCSTRING_DRIFT" for finding in outcome.findings)


class TestAMergeRequestThatOnlyDeletes:
    """The hole the S-03 fix opened, closed in the same round.

    Routing deletions to this tier is useless if the comment is only rendered
    when some file was reviewed. A merge request that deletes a module and
    changes nothing else has no per-file section at all, so the findings were
    computed and then discarded.
    """

    def test_the_comment_is_rendered_for_documentation_findings_alone(self):
        from code_reviewer.application.documentation_service import DocumentationSummary
        from code_reviewer.application.report import render_review_comment
        from code_reviewer.domain.outcome import ReviewOutcome

        findings = _service().review([_change()], {"app.py": ""}).findings
        body = render_review_comment(
            "1.0", ReviewOutcome(), [], documentation=DocumentationSummary(resolved=findings)
        )

        assert "README.md:3" in body
        assert "AI Review Report" in body


class TestARenameYieldsASuggestion:
    """Level 27, step 6 — wired to a review.

    The only documentation edit this repository offers, and the reason it can:
    the diff knows both names, so the substitution is arithmetic. A test in
    `test_architecture.py` asserts nothing in this path can come from a model.
    """

    RENAME = "@@ -1,3 +1,3 @@\n-def start_app(config):\n+def create_app(config):\n     return config\n"

    def _outcome(self, document="# Guide\n\nBoot with `start_app`.\n"):
        return DocumentationService(index=INDEX, documents=[("README.md", document)]).review(
            [FileChange(path="app.py", diff=self.RENAME)], {}
        )

    def test_the_dead_reference_carries_a_suggestion(self):
        outcome = self._outcome()

        assert outcome.suggestions

    def test_the_suggestion_substitutes_the_new_name(self):
        document = "# Guide\n\nBoot with `start_app`.\n"

        applied = self._outcome(document).suggestions[0].applied_to(document)

        assert "create_app" in applied
        assert "start_app" not in applied

    def test_the_finding_is_still_reported(self):
        """The suggestion is additive. A reader who does not click still learns
        the document is stale."""
        assert [f.rule_id for f in self._outcome().findings] == ["DOCS.DEAD_REFERENCE"]

    def test_an_ambiguous_rename_yields_the_finding_and_no_suggestion(self):
        ambiguous = (
            "@@ -1,6 +1,6 @@\n"
            "-def start_app(config):\n"
            "-def start_worker(config):\n"
            "+def create_app(config):\n"
            "+def create_worker(config):\n"
        )

        outcome = DocumentationService(
            index=INDEX, documents=[("README.md", "# Guide\n\nBoot with `start_app`.\n")]
        ).review([FileChange(path="app.py", diff=ambiguous)], {})

        assert outcome.findings
        assert outcome.suggestions == []

    def test_a_removal_that_is_not_a_rename_yields_no_suggestion(self):
        removal = "@@ -1,3 +1,1 @@\n-def start_app(config):\n-    return config\n"

        outcome = DocumentationService(
            index=INDEX, documents=[("README.md", "# Guide\n\nBoot with `start_app`.\n")]
        ).review([FileChange(path="app.py", diff=removal)], {})

        assert outcome.findings
        assert outcome.suggestions == []

    def test_a_clean_document_yields_neither(self):
        outcome = self._outcome("# Guide\n\nNothing relevant here.\n")

        assert outcome.findings == []
        assert outcome.suggestions == []
