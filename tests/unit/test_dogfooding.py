"""The agent runs against its own source, and has to pass.

A review tool that does not meet its own rules is a review tool nobody
believes. Every other analyzer test uses a fixture written to trigger it; this
one uses real code, which is where a rule that fires on every third line
becomes visible (finding G-16).

It is also the cheapest integration test available — no network, no model, no
GitLab — and it runs in a couple of seconds on every push.

The suppression cap is what keeps the assertion honest. Without it, "passing"
could be reached by writing `review-ignore` until the findings stopped, which
is the failure mode suppression was designed to avoid and which a test can
otherwise be used to hide.
"""

import unittest
from pathlib import Path
from typing import ClassVar

from code_reviewer.domain.gate import ReviewGate, ReviewGateResult
from code_reviewer.domain.outcome import ReviewOutcome
from code_reviewer.domain.severity import Severity
from code_reviewer.infrastructure.analyzers.suite import StaticAnalysisSuite
from code_reviewer.infrastructure.config.loader import load_policy

PACKAGE = Path(__file__).resolve().parents[2] / "code_reviewer"

#: Ceiling on reasoned suppressions in the package. Raising it has to be a
#: deliberate edit in a diff someone reviews — which is the point.
#:
#: The five that exist are all one thing: an analyzer reading its own rule
#: table, or a docstring describing the insecure default it exists to have
#: removed. Every other finding the first dogfooding run surfaced was fixed
#: rather than silenced — two analyzer precision bugs, eight discarded error
#: reasons and three over-complex functions.
MAX_SUPPRESSIONS = 6


def _analyse_the_package():
    """Runs the full suite over every module, as the agent would."""
    policy = load_policy()
    suite = StaticAnalysisSuite(policy)
    gate = ReviewGate(policy)
    outcome = ReviewOutcome()

    findings = []
    suppressed = []

    for path in sorted(PACKAGE.rglob("*.py")):
        relative = str(path.relative_to(PACKAGE.parent))
        result = suite.analyze(relative, path.read_text(encoding="utf-8"))

        findings.extend(result.findings)
        suppressed.extend(result.suppressed)
        outcome.record(relative, gate.evaluate("", result.findings))

    return outcome, findings, suppressed


class _Dogfood:
    """Analysed once for the whole module; it is the slowest thing here."""

    outcome = None
    findings: ClassVar[list] = []
    suppressed: ClassVar[list] = []

    @classmethod
    def load(cls):
        if cls.outcome is None:
            cls.outcome, cls.findings, cls.suppressed = _analyse_the_package()
        return cls.outcome, cls.findings, cls.suppressed


class TestThePackagePassesItsOwnGate(unittest.TestCase):
    def setUp(self):
        self.outcome, self.findings, self.suppressed = _Dogfood.load()

    def _describe(self, findings):
        return "\n".join(
            f"  {f.severity.value.upper():8} {f.rule_id:32} {f.location}\n           {f.description}"
            for f in findings
        )

    def test_the_whole_package_was_analysed(self):
        """A test that silently analysed nothing would pass for the wrong reason."""
        self.assertGreater(len(self.outcome.evaluations), 30)

    def test_there_are_no_critical_findings(self):
        critical = [f for f in self.findings if f.severity is Severity.CRITICAL]

        self.assertEqual(critical, [], "\n" + self._describe(critical))

    def test_there_are_no_high_findings(self):
        high = [f for f in self.findings if f.severity is Severity.HIGH]

        self.assertEqual(high, [], "\n" + self._describe(high))

    def test_the_gate_does_not_block(self):
        self.assertIsNot(
            self.outcome.result,
            ReviewGateResult.FAIL,
            "\n" + "\n".join(self.outcome.blocking_issues),
        )


class TestSuppressionsStayDeliberate(unittest.TestCase):
    """ "Passing" must not be reachable by accumulating silences."""

    def setUp(self):
        _, _, self.suppressed = _Dogfood.load()

    def test_suppressions_are_capped(self):
        self.assertLessEqual(
            len(self.suppressed),
            MAX_SUPPRESSIONS,
            f"{len(self.suppressed)} suppressions against a cap of {MAX_SUPPRESSIONS}. "
            "If they are accumulating, either the rule is wrong or the code is.",
        )

    def test_every_suppression_carries_a_reason(self):
        unexplained = [
            f"{item.finding.location} {item.finding.rule_id}"
            for item in self.suppressed
            if not item.directive.is_explained
        ]

        self.assertEqual(unexplained, [], "Suppressed without a reason:\n" + "\n".join(unexplained))


class TestRemainingDebtIsVisible(unittest.TestCase):
    """What is left is technical debt, and a number nobody prints is a number
    nobody watches."""

    def test_the_severity_breakdown_is_reported(self):
        _, findings, _ = _Dogfood.load()

        counts = dict.fromkeys(Severity, 0)
        for finding in findings:
            counts[finding.severity] += 1

        print("\nDogfooding: " + ", ".join(f"{severity.value}={counts[severity]}" for severity in Severity))

        self.assertGreaterEqual(len(findings), 0)


if __name__ == "__main__":
    unittest.main()
