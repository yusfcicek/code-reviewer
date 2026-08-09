"""Grading what the reviewer *said*, against what it was looking at.

Level 12 measured the analyzers and said so in its own non-goals. Nine levels
later the roadmap was still recording "LLM application evaluation" as closed by
it, which is half of a claim about measurement — and half of that claim is the
shape of thing this repository exists to refuse (capability C-02, C-03, C-21).

The question this module answers is deliberately narrow. Not "is this a good
review": that needs a human panel, and a number invented for it would be worse
than no number. The question is **whether the prose is consistent with the facts
it was written about** — the file, its length, the findings the analyzers
produced. That is answerable by arithmetic, recomputable by a reader, and it is
exactly the failure mode a language model has: a confident sentence about
`src/auth.py:412` in a review of forty lines of `src/app.py`.

Everything here is pure. No model call, no network, no clock: an LLM judge would
need an endpoint in CI and would make the score depend on a second unmeasured
model (decision D-1).
"""

import re
from dataclasses import dataclass

from .finding import Finding
from .severity import Severity

#: A `path:line` reference. The path needs a dot-extension so that `TODO:12` and
#: `Risk Assessment: Low` are not read as locations, and the line is bounded to
#: five digits so a port number in a URL cannot become a citation.
_CITATION = re.compile(
    r"(?<![\w/.:-])"  # not mid-word, and not the ':' of a scheme
    r"(?P<path>[\w./-]*[\w-]+\.[A-Za-z][\w]{0,9})"
    r":(?P<line>\d{1,5})"
    r"(?![\w.])"  # not the start of a longer number, nor a domain
)


@dataclass(frozen=True)
class Citation:
    """A `path:line` the prose pointed at."""

    path: str
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"

    @classmethod
    def parse(cls, prose: str) -> tuple["Citation", ...]:
        """Every citation in ``prose``, in the order written.

        Duplicates are kept: a review that cites one wrong location four times
        is wrong four times, and collapsing them would flatter it.
        """
        found = []
        for match in _CITATION.finditer(prose or ""):
            # A range — `app.py:11-14` — is one citation about its first line.
            # Reading it as line 14 would report a defect at a line the review
            # never claimed anything about.
            found.append(cls(path=match.group("path"), line=int(match.group("line"))))
        return tuple(found)


@dataclass(frozen=True)
class NarrationCase:
    """One recorded review, and the facts it was written about.

    Args:
        name: What the case is called, in the report and in the file name.
        file_path: The file the review was about.
        line_count: How long that file is. A citation past it is a defect.
        review: The recorded prose. Graded as it was produced; a corpus that
            re-generates its own subject measures the model's variance and
            calls it review quality (decision D-2).
        findings: What the analyzers produced for that file. The prose's
            severity claims are checked against these.
        prompt_fingerprint: Which prompt produced the review. A floor held
            entirely by recordings from an older prompt is a floor holding
            nothing (decision D-4).
    """

    name: str
    file_path: str
    line_count: int
    review: str
    findings: tuple[Finding, ...] = ()
    prompt_fingerprint: str = ""
    #: Checks this review is *meant* to fail. A corpus whose every review
    #: passes cannot show that the harness is able to fail one, so a case that
    #: declares its own defect makes the instrument testable by the same run
    #: that uses it (contract C-11).
    expected_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A narration case needs a name; the report is read by row.")
        if not self.review.strip():
            raise ValueError(
                f"Case '{self.name}' records no review. There is nothing to grade, and an "
                "entry that grades nothing still counts in every rate in the report."
            )
        if self.line_count < 1:
            raise ValueError(
                f"Case '{self.name}' claims a file of {self.line_count} lines. Nothing can be "
                "cited in it, so every citation check would pass vacuously."
            )

        unknown = sorted(set(self.expected_failures) - CHECK_NAMES)
        if unknown:
            # A typo here would be an expectation nothing can ever meet, which
            # scores as a permanent failure nobody can find the cause of.
            raise ValueError(
                f"Case '{self.name}' expects check(s) {unknown} to fail, and no such check "
                f"exists. The checks are {sorted(CHECK_NAMES)}."
            )

    @property
    def severities(self) -> set[Severity]:
        """The severities the analyzers actually reported for this file."""
        return {finding.severity for finding in self.findings}


#: Headings the prompt's output format asks for. Checked because a consumer
#: reads them: the renderer keeps the model's section under the file's own
#: heading, and a human scans for them. A prompt edit that drops a section is
#: the single most likely regression, and the cheapest to detect (contract C-6).
REQUIRED_SECTIONS = (
    "Security Analysis",
    "Semantic Change Analysis",
    "Impact Analysis",
    "Code Quality",
    "Performance Analysis",
)

#: Claiming a verdict. Rewritten after the self-review measured the first
#: version at three of eight phrasings a model actually writes (S-01): it
#: matched what came to mind while it was being written, and the corpus case
#: built to demonstrate it happened to use one of the three that worked.
#:
#: Deliberately narrow in the other direction: `**SAST Scan Result**: PASS` is
#: the shape the prompt demands, and "the gate blocks on critical findings" is
#: a true statement about the policy. A check that failed those would make the
#: correct sentence unwritable (contract C-4).
_VERDICT_CLAIMS = (
    # A decision about *this* change, in any tense or voice.
    re.compile(
        r"\b(?:this|it|the (?:change|merge|review|pipeline|merge request))\b[^.\n]{0,40}?"
        r"\b(?:is|will\s+be|has\s+been|was)\s+(?:approved|rejected|blocked)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:this|it|the (?:change|merge|review|merge request))\b[^.\n]{0,40}?"
        r"\bblocks?\s+the\s+(?:pipeline|merge|merge request)\b",
        re.I,
    ),
    re.compile(r"\b(?:this|it)\s+will\s+(?:block|fail)\s+the\s+pipeline\b", re.I),
    # The reviewer speaking as the decider.
    re.compile(r"\bI\s+(?:approve|reject|am\s+approving|am\s+rejecting)\b", re.I),
    re.compile(
        r"\b(?:approving|rejecting|blocking)\s+(?:this|the)\s+(?:merge|change|request|merge request)\b", re.I
    ),
    re.compile(r"^\s*(?:blocking|approving)\s+the\s+(?:merge|pipeline)\b", re.I | re.M),
    # The idioms. Short, unambiguous, and the ones a reviewer reaches for.
    re.compile(r"\b(?:LGTM|ship\s+it)\b", re.I),
    re.compile(r"\bdo\s+not\s+merge\b", re.I),
    re.compile(r"\b(?:this\s+)?change\s+is\s+approved\b", re.I),
)

#: Severity words whose use is checked. Upward only, and the asymmetry is the
#: point: claiming CRITICAL with nothing critical behind it invents evidence,
#: while calling something low is an opinion the gate ignores anyway
#: (contract C-5).
_CHECKED_SEVERITIES = (Severity.CRITICAL, Severity.HIGH)


#: Where a severity word is a *claim* rather than an adjective. The first
#: version searched the whole review for the word, and failed reviews that said
#: "high complexity" or "the critical path through this function" (S-04).
#:
#: A claim looks like one of three things: the word in capitals, the word after
#: a label the prompt's format asks for, or the word in parentheses after a
#: finding. Everything else is English.
def _severity_claim(word: str) -> re.Pattern[str]:
    # Case matters for the first alternative and not for the rest, so the
    # insensitivity is scoped rather than applied to the whole pattern: a
    # global `re.I` is what made "high complexity" look like a claim.
    return re.compile(
        r"(?:"
        rf"\b{word.upper()}\b"  # shouted: the review means the severity
        rf"|(?i:(?:severity|risk(?:\s+assessment)?|result|rating|level)\b[^.\n]{{0,24}}?\b{word}\b)"
        rf"|(?i:(?:FAIL|PASS)\s*[-–:]\s*{word}\b)"
        rf"|(?i:\(\s*{word}\s*\))"
        r")"
    )


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict on one review.

    ``detail`` carries the substring that caused a failure, so a reader can act
    on the report without re-reading the review to find what it means.
    """

    check: str
    passed: bool
    detail: str = ""


def citations_are_grounded(case: NarrationCase) -> CheckResult:
    """Every `path:line` in the prose names the file under review, and a line
    that exists in it.

    The headline check. A reader who follows one citation and finds nothing
    there stops believing the whole report, and is right to (contract C-3).
    """
    ungrounded = [
        str(citation)
        for citation in Citation.parse(case.review)
        if citation.path != case.file_path or not 1 <= citation.line <= case.line_count
    ]
    return CheckResult(
        check="citations_are_grounded",
        passed=not ungrounded,
        detail=(
            f"cites {', '.join(sorted(set(ungrounded)))}, which is not a line of "
            f"{case.file_path} (1-{case.line_count})"
            if ungrounded
            else ""
        ),
    )


def the_prose_claims_no_verdict(case: NarrationCase) -> CheckResult:
    """The narration does not claim to have decided anything.

    ADR 0004 has said since Level 4 that findings decide and prose warns.
    Level 20 made a record that says otherwise impossible to build; this makes
    the same claim measurable in the text a human reads.
    """
    claimed = [match.group(0) for pattern in _VERDICT_CLAIMS for match in pattern.finditer(case.review)]
    return CheckResult(
        check="the_prose_claims_no_verdict",
        passed=not claimed,
        detail=f"claims a verdict: {'; '.join(sorted(set(claimed)))}" if claimed else "",
    )


def severity_claims_are_backed(case: NarrationCase) -> CheckResult:
    """A CRITICAL or HIGH in the prose has a finding of that severity behind it."""
    reported = case.severities
    unbacked = [
        severity.value
        for severity in _CHECKED_SEVERITIES
        if _severity_claim(severity.value).search(case.review) and severity not in reported
    ]
    return CheckResult(
        check="severity_claims_are_backed",
        passed=not unbacked,
        detail=(
            f"writes {', '.join(unbacked)} with no finding of that severity behind it" if unbacked else ""
        ),
    )


def severe_findings_are_mentioned(case: NarrationCase) -> CheckResult:
    """Every critical finding is named, by title or by location.

    The opposite defect from inventing a severity, and counted separately
    because the two are fixed by different changes: one is the model being
    imaginative, the other is the model being incurious.
    """
    silent = [
        finding.title
        for finding in case.findings
        if finding.severity is Severity.CRITICAL
        and finding.title.lower() not in case.review.lower()
        and Citation(case.file_path, finding.line_number) not in Citation.parse(case.review)
    ]
    return CheckResult(
        check="severe_findings_are_mentioned",
        passed=not silent,
        detail=f"never mentions {', '.join(sorted(set(silent)))}" if silent else "",
    )


def required_sections_are_present(case: NarrationCase) -> CheckResult:
    """Each heading the prompt's output format asks for appears.

    Matched on the heading text rather than on the whole line, because the
    format decorates them with emoji and a check that pinned the decoration
    would fail on a change that means nothing.
    """
    missing = [section for section in REQUIRED_SECTIONS if section.lower() not in case.review.lower()]
    return CheckResult(
        check="required_sections_are_present",
        passed=not missing,
        detail=f"missing section(s): {', '.join(missing)}" if missing else "",
    )


#: Every check's name, for a case that declares which it is meant to fail.
#: Derived from CHECKS below rather than written twice.


#: Every check, in report order. A tuple rather than a registry decorator: the
#: order is part of the report, and a decorator would make it depend on import
#: order.
CHECKS = (
    citations_are_grounded,
    the_prose_claims_no_verdict,
    severity_claims_are_backed,
    severe_findings_are_mentioned,
    required_sections_are_present,
)


#: The names, for validation. Derived rather than written twice: a second list
#: is a second thing to forget.
CHECK_NAMES = frozenset(check.__name__ for check in CHECKS)
