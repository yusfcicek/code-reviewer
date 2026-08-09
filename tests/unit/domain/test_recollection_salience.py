"""Steps 2 and 3 — how much a memory is worth, and what is dropped."""

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from code_reviewer.domain.recollection import (
    DEFAULT_SALIENCE_FLOOR,
    HALF_LIFE_DAYS,
    Recollection,
    RecollectionKind,
    consolidate,
    forget,
    recall_for,
    retain,
    salience,
)
from code_reviewer.domain.severity import Severity

TODAY = date(2026, 8, 9)


def _recollection(**overrides) -> Recollection:
    seen = overrides.pop("seen", TODAY)
    defaults = {
        "kind": RecollectionKind.FINDING,
        "file_path": "storage/repository.py",
        "rule_id": "SAST.SQL_INJECTION",
        "severity": Severity.MEDIUM,
        "first_seen": seen,
        "last_seen": seen,
        "occurrences": 1,
    }
    return Recollection(**{**defaults, **overrides})


def _days_ago(days: int) -> date:
    return TODAY - timedelta(days=days)


# -- salience ----------------------------------------------------------------


def test_more_sightings_are_more_salient():
    once = salience(_recollection(occurrences=1), TODAY)
    often = salience(_recollection(occurrences=9), TODAY)

    assert often > once


def test_older_is_less_salient():
    fresh = salience(_recollection(seen=TODAY), TODAY)
    stale = salience(_recollection(seen=_days_ago(90)), TODAY)

    assert stale < fresh


def test_one_half_life_ago_is_worth_half():
    now = salience(_recollection(seen=TODAY), TODAY)
    then = salience(_recollection(seen=_days_ago(int(HALF_LIFE_DAYS))), TODAY)

    assert then == pytest.approx(now / 2)


def test_severity_breaks_a_tie_between_equal_histories():
    critical = salience(_recollection(severity=Severity.CRITICAL), TODAY)
    info = salience(_recollection(severity=Severity.INFO), TODAY)

    assert critical > info


def test_an_info_recollection_is_still_worth_something():
    """`Severity.weight` scores INFO at zero, which is right for a quality
    budget and wrong here: it would make every INFO fact score zero and be
    forgotten the moment it was written."""
    assert salience(_recollection(severity=Severity.INFO), TODAY) > 0


def test_a_recollection_from_the_future_does_not_outrank_one_from_today():
    """Clocks are wrong sometimes. A machine an hour ahead should not write an
    entry that outranks everything else forever."""
    future = _recollection(seen=TODAY + timedelta(days=30))

    assert salience(future, TODAY) == pytest.approx(salience(_recollection(seen=TODAY), TODAY))


@given(st.integers(min_value=1, max_value=500), st.integers(min_value=0, max_value=3650))
def test_salience_is_finite_and_positive(occurrences, age):
    value = salience(_recollection(occurrences=occurrences, seen=_days_ago(age)), TODAY)

    assert 0.0 < value < float("inf")


@given(st.integers(min_value=1, max_value=50), st.integers(min_value=0, max_value=365))
def test_salience_is_monotone_in_occurrences_at_a_fixed_age(occurrences, age):
    fewer = salience(_recollection(occurrences=occurrences, seen=_days_ago(age)), TODAY)
    more = salience(_recollection(occurrences=occurrences + 1, seen=_days_ago(age)), TODAY)

    assert more > fewer


# -- forgetting --------------------------------------------------------------


def test_something_stale_enough_is_forgotten():
    ancient = _recollection(severity=Severity.INFO, seen=_days_ago(365))

    assert salience(ancient, TODAY) < DEFAULT_SALIENCE_FLOOR
    assert forget([ancient], TODAY) == []


def test_something_recent_is_kept():
    assert forget([_recollection()], TODAY) == [_recollection()]


def test_a_long_history_survives_a_long_silence():
    """Eleven CRITICAL sightings do not stop mattering because nobody has
    merged anything for two months."""
    persistent = _recollection(severity=Severity.CRITICAL, occurrences=11, seen=_days_ago(60))

    assert forget([persistent], TODAY) == [persistent]


def test_forgetting_preserves_the_order_of_what_it_keeps():
    first = _recollection(rule_id="A.ONE")
    second = _recollection(rule_id="A.TWO")

    assert forget([first, second], TODAY) == [first, second]


# -- retaining ---------------------------------------------------------------


def test_retaining_keeps_the_most_salient():
    weak = _recollection(rule_id="A.WEAK", severity=Severity.INFO, occurrences=1)
    strong = _recollection(rule_id="A.STRONG", severity=Severity.CRITICAL, occurrences=10)

    assert retain([weak, strong], TODAY, limit=1) == [strong]


def test_retaining_is_stable_when_scores_tie():
    """Two runs over one memory must produce the same file. An order that
    depends on dictionary iteration produces a diff on every commit and
    teaches everyone to ignore it."""
    left = _recollection(rule_id="A.LEFT")
    right = _recollection(rule_id="A.RIGHT")

    assert retain([left, right], TODAY, limit=2) == retain([right, left], TODAY, limit=2)


def test_retaining_nothing_is_allowed():
    assert retain([_recollection()], TODAY, limit=0) == []


@given(st.integers(min_value=0, max_value=20))
def test_retaining_never_exceeds_the_limit_or_invents_an_entry(limit):
    memory = [_recollection(rule_id=f"A.RULE{index}") for index in range(7)]

    kept = retain(memory, TODAY, limit=limit)

    assert len(kept) <= limit
    assert len(kept) <= len(memory)
    assert set(kept) <= set(memory)


# -- consolidation -----------------------------------------------------------


def test_consolidation_merges_by_identity_and_leaves_the_rest():
    known = _recollection(occurrences=3, seen=_days_ago(30))
    seen_again = _recollection(occurrences=1, seen=TODAY)
    unrelated = _recollection(rule_id="SAST.WEAK_CRYPTO")

    result = consolidate([known], [seen_again, unrelated])

    assert len(result) == 2
    assert result[0].occurrences == 4
    assert result[0].last_seen == TODAY
    assert result[0].first_seen == _days_ago(30)


def test_consolidation_keeps_what_was_already_there_in_order():
    """The file reads as a history rather than being reshuffled every run."""
    first = _recollection(rule_id="A.ONE")
    second = _recollection(rule_id="A.TWO")
    fresh = _recollection(rule_id="A.THREE")

    result = consolidate([first, second], [fresh])

    assert [item.rule_id for item in result] == ["A.ONE", "A.TWO", "A.THREE"]


def test_consolidating_nothing_into_nothing_is_nothing():
    assert consolidate([], []) == []


# -- recall ------------------------------------------------------------------


def test_this_files_history_comes_before_its_neighbours():
    own = _recollection(file_path="storage/repository.py", rule_id="A.OWN", severity=Severity.INFO)
    neighbour = _recollection(
        file_path="storage/migrations.py", rule_id="A.NEIGHBOUR", severity=Severity.CRITICAL
    )

    recalled = recall_for("storage/repository.py", [neighbour, own], TODAY, limit=2)

    assert [item.rule_id for item in recalled] == ["A.OWN", "A.NEIGHBOUR"]


def test_an_unrelated_directory_is_not_recalled():
    elsewhere = _recollection(file_path="billing/invoice.py", rule_id="A.ELSEWHERE")

    assert recall_for("storage/repository.py", [elsewhere], TODAY, limit=5) == []


def test_a_file_with_no_history_recalls_nothing_rather_than_everything():
    memory = [_recollection(file_path="billing/invoice.py")]

    assert recall_for("http/client.py", memory, TODAY, limit=5) == []


def test_the_root_is_not_a_directory_everything_falls_into():
    """A file at the top level has no directory to generalise from. Treating
    the empty string as one would recall every other top-level file."""
    other_root_file = _recollection(file_path="setup.py", rule_id="A.OTHER")

    assert recall_for("main.py", [other_root_file], TODAY, limit=5) == []


def test_recall_is_capped():
    memory = [_recollection(rule_id=f"A.RULE{index}") for index in range(12)]

    assert len(recall_for("storage/repository.py", memory, TODAY, limit=4)) == 4


def test_recall_is_ordered_by_salience_within_the_file():
    weak = _recollection(rule_id="A.WEAK", severity=Severity.INFO)
    strong = _recollection(rule_id="A.STRONG", severity=Severity.CRITICAL, occurrences=5)

    recalled = recall_for("storage/repository.py", [weak, strong], TODAY, limit=2)

    assert [item.rule_id for item in recalled] == ["A.STRONG", "A.WEAK"]


def test_recalling_for_no_file_returns_nothing():
    assert recall_for("", [_recollection()], TODAY, limit=5) == []
