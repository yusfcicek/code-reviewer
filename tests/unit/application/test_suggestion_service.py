"""Step 3 — proposing, and every reason not to.

A suggestion is a claim about what a file would look like. The cheap way to
check a claim like that is to make it true and look, which is what this service
does — including re-parsing the result, because a suggestion that breaks a
build is worse than the advice it replaced.
"""

from code_reviewer.application.remediation_service import SuggestionService
from code_reviewer.domain.finding import Finding, FindingCategory
from code_reviewer.domain.severity import Severity

CRYPTO = "import hashlib\n\n\ndef digest(value):\n    return hashlib.md5(value).hexdigest()\n"


def _finding(rule="SAST.WEAK_CRYPTO", line=5, path="src/hashing.py") -> Finding:
    return Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.MEDIUM,
        file_path=path,
        line_number=line,
        title="Weak Crypto",
        description="",
        remediation="",
        rule_id=rule,
    )


def _service(**kwargs) -> SuggestionService:
    return SuggestionService(version="2.15.0", **kwargs)


# -- the happy path ----------------------------------------------------------


def test_a_deterministic_finding_gets_its_suggestion():
    suggestions = _service().suggest_for([_finding()], CRYPTO)

    assert len(suggestions) == 1
    assert suggestions[0].recipe == "md5-to-sha256"


def test_the_suggestion_applies_cleanly_to_the_file_as_reviewed():
    (suggestion,) = _service().suggest_for([_finding()], CRYPTO)

    assert "sha256" in suggestion.applied_to(CRYPTO)


# -- what it refuses ---------------------------------------------------------


def test_a_replacement_that_breaks_the_syntax_is_discarded(monkeypatch, caplog):
    """Validated by applying it and re-parsing: a button that leaves the file
    unparseable is worse than the sentence it replaced (contract C-2)."""
    from code_reviewer.domain import fix_recipes as recipes

    monkeypatch.setitem(
        recipes.RECIPES, "SAST.WEAK_CRYPTO", lambda finding, lines: ("    return hashlib.sha256(",)
    )

    with caplog.at_level("WARNING", logger="code_reviewer.application.remediation_service"):
        assert _service().suggest_for([_finding()], CRYPTO) == ()

    assert "parse" in caplog.text.lower()


def test_a_suggestion_for_a_line_that_is_not_there_is_discarded(monkeypatch):
    from code_reviewer.domain import fix_recipes as recipes

    monkeypatch.setitem(recipes.RECIPES, "SAST.WEAK_CRYPTO", lambda finding, lines: ("x = 1",))

    assert _service().suggest_for([_finding(line=99)], CRYPTO) == ()


def test_a_finding_produced_by_an_agent_never_yields_one():
    """Level 20's attribution, applied to a change one click from `main`.
    An unregistered namespace is an agent, and an agent may not author an
    edit somebody will apply without reading it (contract C-3)."""
    assert _service().suggest_for([_finding(rule="MYSTERY.RULE")], CRYPTO) == ()


def test_two_findings_on_one_line_yield_at_most_one_suggestion():
    """Overlapping edits are not applicable, and a reader cannot tell which
    of two buttons they clicked."""
    findings = [_finding(), _finding(rule="SAST.INSECURE_DESERIALIZATION")]

    assert len(_service().suggest_for(findings, "import yaml\n" + CRYPTO)) <= 1


def test_a_finding_about_another_file_is_not_suggested_against_this_one():
    """The source given is the file under review; a finding about a sibling
    would be edited at a line number that means nothing here."""
    assert _service().suggest_for([_finding(path="src/other.py")], CRYPTO, path="src/hashing.py") == ()


def test_no_source_means_no_suggestions():
    """A file the forge could not return is reviewed from the diff alone, and
    an edit proposed against a file nobody read is a guess."""
    assert _service().suggest_for([_finding()], "") == ()


def test_a_non_python_file_is_left_alone():
    """The syntax check is `ast.parse`, so anything it cannot parse would be
    discarded anyway — declining early says why."""
    assert _service().suggest_for([_finding(path="config.yaml")], CRYPTO, path="config.yaml") == ()


def test_nothing_raises_when_a_recipe_explodes(monkeypatch):
    from code_reviewer.domain import fix_recipes as recipes

    def explode(finding, lines):
        raise RuntimeError("boom")

    monkeypatch.setitem(recipes.RECIPES, "SAST.WEAK_CRYPTO", explode)

    assert _service().suggest_for([_finding()], CRYPTO) == ()


# -- S-02: only lines the merge request touched ------------------------------
#
# A note carries a position, and a position has to name a line in the diff. An
# edit proposed on an untouched line is rejected by the platform — and it is a
# change of subject rather than a fix.

DIFF_TOUCHING_LINE_5 = (
    "@@ -1,5 +1,5 @@\n import hashlib\n \n \n def digest(value):\n"
    "+    return hashlib.md5(value).hexdigest()\n"
)
DIFF_TOUCHING_LINE_1 = "@@ -1,1 +1,1 @@\n+import hashlib\n"


def test_a_finding_on_a_changed_line_is_suggested():
    suggestions = _service().suggest_for(
        [_finding()], CRYPTO, path="src/hashing.py", diff=DIFF_TOUCHING_LINE_5
    )

    assert len(suggestions) == 1


def test_a_finding_on_a_line_the_merge_request_did_not_touch_is_not():
    """The platform would reject the note, and the rejection is a warning
    nobody reads. Proposing nothing is the honest answer."""
    suggestions = _service().suggest_for(
        [_finding()], CRYPTO, path="src/hashing.py", diff=DIFF_TOUCHING_LINE_1
    )

    assert suggestions == ()


def test_without_a_diff_every_line_is_eligible():
    """A caller with no diff — a test, or a forge that returned none — gets
    the old behaviour rather than silence."""
    assert len(_service().suggest_for([_finding()], CRYPTO, path="src/hashing.py")) == 1


def test_a_diff_that_cannot_be_parsed_suggests_nothing():
    """Fail closed: an unparseable diff means the eligible lines are unknown,
    and proposing against unknown is how the platform gets a note it refuses."""
    assert _service().suggest_for([_finding()], CRYPTO, path="src/hashing.py", diff="+ garbage\n") == ()


# -- S-06: which file a suggestion is about ----------------------------------


def test_the_subject_is_refused_rather_than_guessed_from_the_first_finding():
    """With findings from two files and no path, the old code took the first
    finding's file as the subject for all of them — so which file was edited
    depended on list order."""
    other = _finding(path="src/other.py")

    assert _service().suggest_for([other, _finding()], CRYPTO) == ()
