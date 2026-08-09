"""Step 2 — running the checks, defensively."""

import threading

from code_reviewer.application.health import ReadinessProbe
from code_reviewer.domain.health import CheckResult


def test_every_registered_check_produces_a_result():
    probe = ReadinessProbe()
    probe.register("a", lambda: CheckResult.ok("a")).register("b", lambda: CheckResult.ok("b"))

    readiness = probe.run()

    assert [result.name for result in readiness.results] == ["a", "b"]
    assert readiness.is_ready


def test_a_check_that_raises_fails_only_itself():
    """A readiness endpoint that returns 500 because a check had a bug is a
    readiness endpoint that takes the deployment down for a reason unrelated
    to readiness."""

    def explode() -> CheckResult:
        raise RuntimeError("the client is not configured")

    probe = ReadinessProbe({"broken": explode, "fine": lambda: CheckResult.ok("fine")})

    readiness = probe.run()

    assert not readiness.is_ready
    assert len(readiness.failures) == 1
    assert "RuntimeError" in readiness.failures[0].reason


def test_a_check_that_raises_does_not_leak_its_message():
    """An exception's message is built from whatever the process was holding."""

    def explode() -> CheckResult:
        raise RuntimeError("token glpat-AAAABBBBCCCC was rejected")

    readiness = ReadinessProbe({"broken": explode}).run()

    assert "glpat" not in readiness.summary()


def test_a_check_that_returns_the_wrong_shape_is_a_failed_check():
    """A bug in the check, reported as one, rather than let through as
    'ready'."""
    readiness = ReadinessProbe({"odd": lambda: True}).run()

    assert not readiness.is_ready
    assert "did not return a result" in readiness.failures[0].reason


def test_a_probe_with_no_checks_is_ready():
    assert ReadinessProbe().run().is_ready


def test_registering_returns_the_probe_so_a_builder_reads_as_one_expression():
    probe = ReadinessProbe().register("a", lambda: CheckResult.ok("a"))

    assert isinstance(probe, ReadinessProbe)
    assert probe.check_names == ("a",)


def test_registering_the_same_name_twice_replaces_it():
    probe = ReadinessProbe()
    probe.register("a", lambda: CheckResult.failed("a", "no"))
    probe.register("a", lambda: CheckResult.ok("a"))

    assert probe.run().is_ready


def test_the_pair_the_application_asks_for():
    probe = ReadinessProbe({"gitlab": lambda: CheckResult.failed("gitlab", "GITLAB_TOKEN is not set")})

    ready, reason = probe.as_probe()()

    assert not ready
    assert "GITLAB_TOKEN" in reason


def test_a_probe_survives_being_called_from_several_threads():
    """It is what a probe *is*: several things asking at once."""
    probe = ReadinessProbe({f"check-{index}": _always_ok(index) for index in range(6)})
    answers = []
    lock = threading.Lock()

    def ask():
        readiness = probe.run()
        with lock:
            answers.append(readiness.is_ready)

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert answers == [True] * 8


def _always_ok(index: int):
    return lambda: CheckResult.ok(f"check-{index}")
