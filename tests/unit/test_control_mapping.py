"""Step 6 — the mapping, and everything it refuses to claim.

Level 20 refused a compliance framework because *"those are an organisation's,
and inventing one here would be guessing at somebody else's obligations."* That
is still true of the *obligations*. It was never true of the *mapping*: an
auditor asking "show me that changes are reviewed for injection flaws" is
currently handed rule ids and left to derive the answer from source code, once
per organisation.

So one named, publicly documented catalogue ships as **data**, and the module
that reads it will not say the word "compliant".
"""

from pathlib import Path

import pytest

from code_reviewer.application.compliance import (
    CatalogueError,
    ControlCatalogue,
    coverage,
    load_catalogue,
    render_coverage,
)
from code_reviewer.application.governance import PRODUCERS
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity

CATALOGUE = Path("code_reviewer/infrastructure/config/controls.yaml")


def _finding(rule_id, severity=Severity.HIGH):
    return Finding(
        category=FindingCategory.SECURITY,
        severity=severity,
        file_path="app.py",
        line_number=1,
        title="Something",
        description="",
        remediation="",
        rule_id=rule_id,
    )


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue(CATALOGUE)


class TestTheCatalogueNamesItself:
    def test_it_states_its_name(self, catalogue):
        assert catalogue.name

    def test_it_states_its_version(self, catalogue):
        """A control identifier means nothing without the revision it is from."""
        assert catalogue.version

    def test_it_states_its_publisher(self, catalogue):
        assert catalogue.publisher

    def test_it_states_where_it_can_be_read(self, catalogue):
        """A mapping to a catalogue nobody can look up is a mapping to nothing."""
        assert catalogue.reference.startswith("http")


class TestCoverageOfTheNamespaces:
    def test_every_namespace_this_system_emits_is_mapped(self, catalogue):
        """AC-11, and the same completeness test Level 20 wrote for the
        attribution table: a new namespace becomes a red test rather than a
        silent omission."""
        for namespace in PRODUCERS:
            assert catalogue.controls_for(namespace), f"{namespace} maps to no control"

    def test_an_unknown_namespace_maps_to_nothing(self, catalogue):
        assert catalogue.controls_for("INVENTED") == ()

    def test_every_mapped_control_is_described(self, catalogue):
        """A control id with no text is an identifier an auditor has to look up
        somewhere else, which is the work this file exists to save."""
        for namespace in PRODUCERS:
            for control in catalogue.controls_for(namespace):
                assert catalogue.describe(control), control


class TestWhatARunCovers:
    def test_a_finding_covers_the_controls_its_namespace_maps_to(self, catalogue):
        report = coverage(catalogue, [_finding("SAST.SQL_INJECTION")])

        assert report.evidenced
        assert all(entry.findings for entry in report.evidenced)

    def test_a_control_with_no_finding_is_reported_as_having_no_evidence(self, catalogue):
        """The answer an auditor actually needs. Omitting it silently is how a
        report claims coverage it does not have."""
        report = coverage(catalogue, [])

        assert report.unevidenced
        assert not report.evidenced

    def test_the_counts_are_per_control_not_per_finding(self, catalogue):
        report = coverage(catalogue, [_finding("SAST.SQL_INJECTION"), _finding("SAST.WEAK_CRYPTO")])
        entry = next(iter(report.evidenced))

        assert entry.findings >= 2

    def test_a_finding_whose_namespace_is_unmapped_is_reported_as_unmapped(self, catalogue):
        """AC-12. Dropping it would let a namespace disappear from the report
        by being new."""
        report = coverage(catalogue, [_finding("INVENTED.RULE")])

        assert "INVENTED" in report.unmapped

    def test_a_finding_with_no_namespace_is_unmapped_rather_than_ignored(self, catalogue):
        report = coverage(catalogue, [_finding("bare_rule_id")])

        assert report.unmapped


class TestTheReportRefusesToOverclaim:
    def test_it_never_says_compliant(self, catalogue):
        """AC-13. This repository cannot know an organisation's obligations, and
        a report that implies it has met them is the documentation defect Level
        23 exists to catch, in the one place it would be expensive."""
        rendered = render_coverage(coverage(catalogue, [_finding("SAST.SQL_INJECTION")]))

        assert "compliant" not in rendered.lower()

    def test_it_never_says_certified(self, catalogue):
        rendered = render_coverage(coverage(catalogue, [_finding("SAST.SQL_INJECTION")]))

        assert "certified" not in rendered.lower()

    def test_it_names_the_catalogue_and_its_version(self, catalogue):
        rendered = render_coverage(coverage(catalogue, []))

        assert catalogue.name in rendered
        assert catalogue.version in rendered

    def test_it_says_what_it_is_evidence_of_rather_than_what_it_proves(self, catalogue):
        rendered = render_coverage(coverage(catalogue, [_finding("SAST.SQL_INJECTION")]))

        assert "evidence" in rendered.lower()

    def test_a_control_with_no_evidence_is_listed_as_such(self, catalogue):
        rendered = render_coverage(coverage(catalogue, []))

        assert "no evidence" in rendered.lower()

    def test_the_rendering_carries_no_file_paths(self, catalogue):
        """Coverage is about controls. A path belongs in the review."""
        rendered = render_coverage(coverage(catalogue, [_finding("SAST.SQL_INJECTION")]))

        assert "app.py" not in rendered


class TestLoading:
    def test_a_missing_file_is_refused_rather_than_treated_as_empty(self, tmp_path):
        with pytest.raises(CatalogueError):
            load_catalogue(tmp_path / "absent.yaml")

    def test_a_catalogue_with_no_version_is_refused(self, tmp_path):
        path = tmp_path / "controls.yaml"
        path.write_text("name: X\npublisher: Y\nreference: http://x\ncontrols: {}\n")

        with pytest.raises(CatalogueError):
            load_catalogue(path)

    def test_a_catalogue_that_is_not_a_mapping_is_refused(self, tmp_path):
        path = tmp_path / "controls.yaml"
        path.write_text("- just\n- a\n- list\n")

        with pytest.raises(CatalogueError):
            load_catalogue(path)

    def test_the_shipped_catalogue_is_replaceable(self, tmp_path):
        """It is data, not code. An organisation swaps the file."""
        path = tmp_path / "controls.yaml"
        path.write_text(
            "name: House Rules\nversion: '1'\npublisher: Us\nreference: http://example.invalid\n"
            "controls:\n  HR-1:\n    description: We look at the code.\n    namespaces: [SAST]\n"
        )

        loaded = load_catalogue(path)

        assert loaded.name == "House Rules"
        assert loaded.controls_for("SAST") == ("HR-1",)


def test_the_catalogue_type_can_be_built_without_a_file():
    catalogue = ControlCatalogue(
        name="X",
        version="1",
        publisher="Y",
        reference="http://x",
        mapping={"SAST": ("A-1",)},
        descriptions={"A-1": "Something"},
    )

    assert catalogue.controls_for("SAST") == ("A-1",)
