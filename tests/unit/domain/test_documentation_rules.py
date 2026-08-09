"""Step 3 — the deterministic tier, and everything it declines to say.

Each rule ends in a lookup that succeeds or fails. Nothing here is a judgement
about writing; a dead reference is a fact, and the rules that cannot establish
a fact report nothing.
"""

from code_reviewer.domain.documentation import SymbolIndex, claims_in, documentation_defects

INDEX = SymbolIndex(
    names=frozenset({"create_app", "AgentExecutor", "drain"}),
    signatures={"create_app": ("config", "worker"), "drain": ("worker", "seconds")},
    options=frozenset({"--strict"}),
    environment=frozenset({"CI_PROJECT_ID"}),
)


def _defects(text, index=INDEX):
    return documentation_defects(claims_in(text), index)


def _rules(text, index=INDEX):
    return [defect.rule for defect in _defects(text, index)]


def test_a_symbol_the_tree_does_not_define_is_a_dead_reference():
    assert _rules("Calls `create_apps` at boot.") == ["DEAD_REFERENCE"]


def test_a_symbol_the_tree_defines_is_not_reported():
    assert _rules("Calls `create_app` at boot.") == []


def test_the_defect_names_the_symbol_and_where_it_was_written():
    defect = _defects("## Boot\n\nCalls `create_apps`.\n")[0]

    assert defect.subject == "create_apps"
    assert defect.line == 3
    assert defect.heading == "Boot"


def test_a_documented_signature_that_does_not_match_is_reported():
    assert _rules("Call `create_app(config, worker, extra)`.") == ["SIGNATURE_MISMATCH"]


def test_a_documented_signature_that_matches_is_not_reported():
    assert _rules("Call `create_app(config, worker)`.") == []


def test_a_signature_claim_for_an_unknown_symbol_is_a_dead_reference():
    """One defect, not two. The signature is unknowable until the name is."""
    assert _rules("Call `create_apps(config)`.") == ["DEAD_REFERENCE"]


def test_a_signature_claim_for_something_that_is_not_a_function_is_not_reported():
    """Comparing parameter names against a class is comparing nothing."""
    assert _rules("See `AgentExecutor(config)`.") == []


def test_the_signature_defect_names_both_lists_and_no_prose():
    defect = _defects("Call `create_app(config, worker, extra)`.")[0]

    assert "extra" in defect.detail
    assert "documented" in defect.detail.lower()


def test_an_unknown_flag_is_reported():
    assert _rules("Pass `--loose` to relax.") == ["UNKNOWN_OPTION"]


def test_a_known_flag_is_not_reported():
    assert _rules("Pass `--strict` to fail.") == []


def test_an_unknown_environment_name_is_reported():
    assert _rules("Reads `CI_PROJECT_SLUG`.") == ["UNKNOWN_OPTION"]


def test_a_known_environment_name_is_not_reported():
    assert _rules("Reads `CI_PROJECT_ID`.") == []


def test_a_fenced_example_that_does_not_parse_is_reported():
    assert _rules("```python\ndef (:\n```\n") == ["BROKEN_EXAMPLE"]


def test_a_fenced_example_that_parses_is_not_reported():
    assert _rules("```python\nvalue = 1\n```\n") == []


def test_a_fenced_example_is_not_checked_for_symbols_it_names():
    """An example may reference a library this repository does not define."""
    assert _rules("```python\nimport requests\n\nrequests.get('http://x')\n```\n") == []


def test_a_correct_document_yields_nothing_at_all():
    text = "# Title\n\nCall `create_app(config, worker)` and pass `--strict`.\nReads `CI_PROJECT_ID`.\n"

    assert _defects(text) == []


def test_an_empty_index_reports_nothing():
    """AC-8's other half, and the reason the level survives a bad build."""
    text = "Calls `create_apps` and passes `--nonsense`.\n"

    assert _defects(text, SymbolIndex.EMPTY) == []


def test_an_empty_index_still_reports_a_broken_example():
    """Syntax needs no index, so this rule keeps working when the others cannot."""
    assert _rules("```python\ndef (:\n```\n", SymbolIndex.EMPTY) == ["BROKEN_EXAMPLE"]


def test_no_defect_carries_a_sentence_from_the_document():
    """AC-14 — identifiers, never content, now that the content is English."""
    text = "# Title\n\nThe boot path is delicate, so `create_apps` is called last.\n"

    for defect in _defects(text):
        assert "delicate" not in defect.detail
        assert "delicate" not in defect.subject
