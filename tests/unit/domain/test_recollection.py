"""Step 1 — what a review remembers, and when two facts are one fact."""

from datetime import date

import pytest

from code_reviewer.domain.recollection import Recollection, RecollectionKind
from code_reviewer.domain.severity import Severity

JANUARY = date(2026, 1, 10)
FEBRUARY = date(2026, 2, 10)
MARCH = date(2026, 3, 10)


def _recollection(**overrides) -> Recollection:
    defaults = {
        "kind": RecollectionKind.FINDING,
        "file_path": "storage/repository.py",
        "rule_id": "SAST.SQL_INJECTION",
        "severity": Severity.CRITICAL,
        "first_seen": JANUARY,
        "last_seen": JANUARY,
        "occurrences": 1,
    }
    return Recollection(**{**defaults, **overrides})


def test_a_recollection_carries_what_it_is_about():
    remembered = _recollection()

    assert remembered.kind is RecollectionKind.FINDING
    assert remembered.file_path == "storage/repository.py"
    assert remembered.rule_id == "SAST.SQL_INJECTION"
    assert remembered.occurrences == 1


def test_identity_is_the_kind_the_file_and_the_rule():
    assert _recollection().identity == (
        RecollectionKind.FINDING,
        "storage/repository.py",
        "SAST.SQL_INJECTION",
    )


def test_a_rule_that_moved_lines_is_still_the_same_fact():
    """A refactor that shifts a function down two lines must not reset every
    count in the file. Line number is not part of identity, and neither is
    severity — the same rule reported at a different grade is the same rule
    having an opinion."""
    assert _recollection().identity == _recollection(severity=Severity.LOW).identity


def test_a_different_rule_in_the_same_file_is_a_different_fact():
    assert _recollection().identity != _recollection(rule_id="SAST.WEAK_CRYPTO").identity


def test_a_suppression_and_a_finding_of_the_same_rule_are_different_facts():
    """One is 'this keeps happening'; the other is 'somebody decided'."""
    suppression = _recollection(kind=RecollectionKind.SUPPRESSION)

    assert suppression.identity != _recollection().identity


# -- merging -----------------------------------------------------------------


def test_merging_two_sightings_sums_their_occurrences():
    merged = _recollection(occurrences=3).merge(_recollection(occurrences=2))

    assert merged.occurrences == 5


def test_merging_keeps_the_earliest_first_seen_and_the_latest_last_seen():
    early = _recollection(first_seen=JANUARY, last_seen=JANUARY)
    late = _recollection(first_seen=FEBRUARY, last_seen=MARCH)

    merged = early.merge(late)

    assert merged.first_seen == JANUARY
    assert merged.last_seen == MARCH


def test_merging_keeps_the_worst_severity_seen():
    """The rule reported CRITICAL once and LOW twice. What a reader needs to
    know is that it has been CRITICAL here."""
    merged = _recollection(severity=Severity.LOW).merge(_recollection(severity=Severity.CRITICAL))

    assert merged.severity is Severity.CRITICAL


def test_merging_prefers_the_more_recent_reason():
    """A suppression's reason can be rewritten. The current one is the one
    somebody would read in the file."""
    old = _recollection(kind=RecollectionKind.SUPPRESSION, reason="old reason", last_seen=JANUARY)
    new = _recollection(kind=RecollectionKind.SUPPRESSION, reason="new reason", last_seen=MARCH)

    assert old.merge(new).reason == "new reason"
    assert new.merge(old).reason == "new reason"


def test_merging_keeps_a_reason_when_the_newer_sighting_has_none():
    old = _recollection(kind=RecollectionKind.SUPPRESSION, reason="written down", last_seen=JANUARY)
    new = _recollection(kind=RecollectionKind.SUPPRESSION, reason="", last_seen=MARCH)

    assert old.merge(new).reason == "written down"


def test_merging_unrelated_facts_is_refused():
    """A silent merge of two different rules is the bug this class exists to
    make impossible."""
    with pytest.raises(ValueError):
        _recollection().merge(_recollection(rule_id="SAST.WEAK_CRYPTO"))


def test_a_recollection_seen_no_times_is_refused():
    with pytest.raises(ValueError):
        _recollection(occurrences=0)


def test_a_recollection_that_ended_before_it_began_is_refused():
    with pytest.raises(ValueError):
        _recollection(first_seen=MARCH, last_seen=JANUARY)


def test_the_directory_is_derived_from_the_path():
    assert _recollection().directory == "storage"
    assert _recollection(file_path="main.py").directory == ""
    assert _recollection(file_path="a/b/c.py").directory == "a/b"
