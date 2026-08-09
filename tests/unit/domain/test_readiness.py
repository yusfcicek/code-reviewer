"""Step 1 — what readiness is."""

import pytest

from code_reviewer.domain.health import CheckResult, Readiness, combine


def test_a_passing_check_carries_no_reason():
    result = CheckResult.ok("gitlab")

    assert result.passed
    assert result.reason == ""


def test_a_failing_check_must_say_why():
    with pytest.raises(ValueError):
        CheckResult(name="gitlab", passed=False)


def test_a_passing_check_may_not_carry_a_failure_reason():
    with pytest.raises(ValueError):
        CheckResult(name="gitlab", passed=True, reason="but actually")


def test_everything_passing_is_ready():
    readiness = combine([CheckResult.ok("a"), CheckResult.ok("b")])

    assert readiness.is_ready
    assert readiness.reasons == ()
    assert readiness.summary() == "ready"


def test_every_failure_is_reported_not_the_first():
    """A probe that names one missing variable at a time costs a deploy per
    variable."""
    readiness = combine(
        [
            CheckResult.failed("gitlab", "GITLAB_TOKEN is not set"),
            CheckResult.ok("policy"),
            CheckResult.failed("model", "VLLM_BASE_URL is not set"),
            CheckResult.failed("workspace", "the workspace root does not exist"),
        ]
    )

    assert not readiness.is_ready
    assert len(readiness.reasons) == 3


def test_reasons_come_back_in_check_name_order():
    """A reason list whose order depends on registration is a diff nobody can
    compare."""
    readiness = combine(
        [
            CheckResult.failed("zebra", "z"),
            CheckResult.failed("alpha", "a"),
            CheckResult.failed("middle", "m"),
        ]
    )

    assert [result.name for result in readiness.failures] == ["alpha", "middle", "zebra"]


def test_the_summary_names_the_failing_checks():
    readiness = combine([CheckResult.failed("gitlab", "GITLAB_TOKEN is not set"), CheckResult.ok("policy")])

    summary = readiness.summary()

    assert summary.startswith("not ready")
    assert "gitlab" in summary
    assert "GITLAB_TOKEN is not set" in summary
    assert "policy" not in summary


def test_a_probe_with_nothing_to_check_is_ready():
    """A process with nothing to check has nothing wrong with it, and
    defaulting to 'not ready' would make the first deployment of anything fail
    for no stated reason."""
    assert Readiness().is_ready
    assert Readiness().summary() == "ready"


def test_readiness_is_a_value():
    assert combine([CheckResult.ok("a")]) == combine([CheckResult.ok("a")])
