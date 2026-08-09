"""Step 3 — the deterministic tier, and everything it declines to say.

Every rule ends in something the change *proves*. That is not where this module
started: the first cut resolved every backtick against the tree, and a dry run
over this repository produced twenty-five findings in the README of which
almost all were wrong — `yaml.safe_load` and `hashlib.md5` live in libraries,
`ConfigMap` is a Kubernetes noun, `--cov` is a pytest flag, `id_rsa` is a
filename. None of that is distinguishable from a stale reference by looking at
the text.

The diff is what distinguishes them, so the scope is not an optimisation. It is
the difference between a fact and a resemblance.
"""

from code_reviewer.domain.documentation import ChangeScope, SymbolIndex, claims_in, documentation_defects

INDEX = SymbolIndex(
    names=frozenset({"create_app", "AgentExecutor", "drain"}),
    signatures={"create_app": ("config", "worker"), "drain": ("worker", "seconds")},
    options=frozenset({"--strict"}),
    environment=frozenset({"CI_PROJECT_ID"}),
)

#: A change that removed a function, an option and an environment variable.
REMOVED = ChangeScope(
    removed=frozenset({"start_app", "--legacy", "REVIEW_LEGACY_MODE"}),
    touched=frozenset({"start_app", "--legacy", "REVIEW_LEGACY_MODE"}),
)

#: A change that edited the document itself.
EDITED = ChangeScope(document_changed=True)


def _defects(text, index=INDEX, scope=REMOVED):
    return documentation_defects(claims_in(text), index, scope)


def _rules(text, index=INDEX, scope=REMOVED):
    return [defect.rule for defect in _defects(text, index, scope)]


class TestDeadReferences:
    def test_a_symbol_the_change_removed_is_reported(self):
        assert _rules("Calls `start_app` at boot.") == ["DEAD_REFERENCE"]

    def test_the_defect_names_the_symbol_and_where_it_was_written(self):
        defect = _defects("## Boot\n\nCalls `start_app`.\n")[0]

        assert defect.subject == "start_app"
        assert defect.line == 3
        assert defect.heading == "Boot"

    def test_a_symbol_the_change_did_not_touch_is_never_reported(self):
        """`hashlib.md5` and `ConfigMap` are not this repository's to define."""
        for absent in ("hashlib.md5", "ConfigMap", "some_other_name"):
            assert _rules(f"See `{absent}`.") == [], absent

    def test_a_removed_name_that_still_resolves_is_not_reported(self):
        """A function moved between modules is not a dead reference."""
        scope = ChangeScope(removed=frozenset({"create_app"}))

        assert _rules("Calls `create_app`.", scope=scope) == []

    def test_editing_the_document_does_not_make_every_name_dead(self):
        """The direction that would report a library call as a defect."""
        assert _rules("Calls `hashlib.md5` and `start_app`.", scope=EDITED) == []


class TestSignatures:
    def test_a_documented_signature_that_does_not_match_is_reported(self):
        scope = ChangeScope(touched=frozenset({"create_app"}))

        assert _rules("Call `create_app(config, worker, extra)`.", scope=scope) == ["SIGNATURE_MISMATCH"]

    def test_a_documented_signature_that_matches_is_not_reported(self):
        scope = ChangeScope(touched=frozenset({"create_app"}))

        assert _rules("Call `create_app(config, worker)`.", scope=scope) == []

    def test_an_edited_document_has_all_its_signatures_checked(self):
        """The second direction of C-1: the author is right there."""
        assert _rules("Call `create_app(config)`.", scope=EDITED) == ["SIGNATURE_MISMATCH"]

    def test_a_signature_the_change_did_not_touch_is_not_checked(self):
        assert _rules("Call `create_app(config)`.") == []

    def test_a_signature_claim_for_a_removed_symbol_is_a_dead_reference(self):
        """One defect, not two. The signature is unknowable until the name is."""
        assert _rules("Call `start_app(config)`.") == ["DEAD_REFERENCE"]

    def test_a_signature_claim_for_something_that_is_not_a_function_is_not_reported(self):
        assert _rules("See `AgentExecutor(config)`.", scope=EDITED) == []

    def test_a_dotted_name_from_another_library_is_not_compared(self):
        """`yaml.load` resolved to a `load` defined here, and the rule then
        reported a library's signature as this project's mistake."""
        index = SymbolIndex(names=frozenset({"load"}), signatures={"load": ("path",)})

        assert _rules("Call `yaml.load(stream)`.", index=index, scope=EDITED) == []

    def test_the_signature_defect_names_both_lists_and_no_prose(self):
        defect = _defects("Call `create_app(config, worker, extra)`.", scope=EDITED)[0]

        assert "extra" in defect.detail
        assert "documented" in defect.detail.lower()


class TestOptionsAndEnvironment:
    def test_a_removed_flag_is_reported(self):
        assert _rules("Pass `--legacy` to relax.") == ["UNKNOWN_OPTION"]

    def test_a_flag_this_project_never_owned_is_not_reported(self):
        """`--cov` is pytest's and `--no-ff` is git's; both appear in this
        repository's own CONTRIBUTING.md."""
        for foreign in ("--cov", "--no-ff"):
            assert _rules(f"Run it with `{foreign}`.") == [], foreign

    def test_a_removed_environment_name_is_reported(self):
        assert _rules("Reads `REVIEW_LEGACY_MODE`.") == ["UNKNOWN_OPTION"]

    def test_an_environment_name_the_change_did_not_touch_is_not_reported(self):
        assert _rules("Reads `CI_PROJECT_SLUG`.") == []

    def test_a_removed_name_that_still_exists_is_not_reported(self):
        scope = ChangeScope(removed=frozenset({"--strict"}))

        assert _rules("Pass `--strict`.", scope=scope) == []


class TestExamples:
    def test_a_fenced_example_in_an_edited_document_that_does_not_parse_is_reported(self):
        assert _rules("```python\ndef (:\n```\n", scope=EDITED) == ["BROKEN_EXAMPLE"]

    def test_a_fenced_example_that_parses_is_not_reported(self):
        assert _rules("```python\nvalue = 1\n```\n", scope=EDITED) == []

    def test_an_untouched_document_is_not_scanned_for_broken_examples(self):
        """Otherwise every run reports the same ancient block forever."""
        assert _rules("```python\ndef (:\n```\n") == []

    def test_an_example_is_not_checked_for_the_symbols_it_names(self):
        text = "```python\nimport requests\n\nrequests.get('http://x')\n```\n"

        assert _rules(text, scope=EDITED) == []

    def test_a_broken_example_is_reported_even_with_no_index(self):
        """Syntax needs nothing read, so this rule survives a failed index."""
        assert _rules("```python\ndef (:\n```\n", index=SymbolIndex.EMPTY, scope=EDITED) == ["BROKEN_EXAMPLE"]


class TestSilences:
    def test_a_correct_document_yields_nothing_at_all(self):
        text = "# Title\n\nCall `create_app(config, worker)` and pass `--strict`.\nReads `CI_PROJECT_ID`.\n"

        assert _defects(text, scope=EDITED) == []

    def test_an_empty_index_reports_nothing(self):
        """The reason the level survives a shallow checkout."""
        assert _defects("Calls `start_app` and passes `--legacy`.\n", index=SymbolIndex.EMPTY) == []

    def test_a_change_that_removed_nothing_reports_nothing(self):
        assert _defects("Calls `start_app`.\n", scope=ChangeScope()) == []

    def test_no_defect_carries_a_sentence_from_the_document(self):
        """AC-14 — identifiers, never content, now that the content is English."""
        text = "# Title\n\nThe boot path is delicate, so `start_app` is called last.\n"

        for defect in _defects(text):
            assert "delicate" not in defect.detail
            assert "delicate" not in defect.subject


def test_an_indented_fence_is_dedented_before_it_is_parsed():
    """A fence inside a list item carries the list's indentation, and
    `ast.parse` calls that an IndentationError. This repository's own
    CONTRIBUTING.md has one, and it was the last false positive in the dry run."""
    text = "1. Like this:\n\n   ```python\n   value = 1\n   ```\n"

    assert documentation_defects(claims_in(text), INDEX, EDITED) == []
