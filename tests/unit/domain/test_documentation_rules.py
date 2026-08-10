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
    return documentation_defects(claims_in(text, named=scope.names), index, scope)


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


class TestTheScopeOutranksTheShapeTest:
    """Self-review S-02 — two safeguards, and the blunt one cancelled the sharp one.

    `_symbol_shaped` refuses a bare lowercase word, so `async` and `false` in a
    README are not read as symbols. That was right when every backtick was
    resolved against the tree. Since the scope rework it is wrong: a name the
    diff *removed* is direct evidence that the name was this repository's, and
    the shape test threw that evidence away.

    Measured against the real index: 113 of 648 bare functions (17 %) were
    invisible — `add`, `analyze`, `bind`, `cases`, `claim`, `covers`.
    """

    PLAIN = ChangeScope(removed=frozenset({"drain"}), touched=frozenset({"drain"}))
    #: `drain` is gone from the tree, which is what makes the document stale.
    WITHOUT_DRAIN = SymbolIndex(names=frozenset({"create_app"}), signatures={"create_app": ("config",)})

    def test_a_plain_lowercase_name_the_change_removed_is_reported(self):
        assert _rules("Call `drain` on exit.", index=self.WITHOUT_DRAIN, scope=self.PLAIN) == [
            "DEAD_REFERENCE"
        ]

    def test_the_same_name_is_still_ignored_when_the_change_did_not_remove_it(self):
        """The shape test still does its job everywhere the diff proves nothing."""
        assert _rules("Call `drain` on exit.", index=self.WITHOUT_DRAIN, scope=ChangeScope()) == []

    def test_an_english_word_the_change_happens_to_have_removed_is_still_reported(self):
        """Accepted consequence: if a change deletes something called `false`,
        a document saying `false` is reported. The diff said it was ours."""
        scope = ChangeScope(removed=frozenset({"false"}), touched=frozenset({"false"}))

        assert _rules("Set it to `false`.", index=self.WITHOUT_DRAIN, scope=scope) == ["DEAD_REFERENCE"]

    def test_an_ordinary_word_is_untouched_when_nothing_removed_it(self):
        for word in ("async", "false", "critical", "auto"):
            assert _rules(f"Set it to `{word}`.", scope=EDITED) == [], word

    def test_a_removed_plain_name_that_still_resolves_is_not_reported(self):
        index = SymbolIndex(names=frozenset({"drain"}), signatures={"drain": ("worker",)})

        assert _rules("Call `drain`.", index=index, scope=self.PLAIN) == []

    def test_a_plain_name_signature_is_compared_when_the_change_touched_it(self):
        index = SymbolIndex(names=frozenset({"drain"}), signatures={"drain": ("worker", "seconds")})
        scope = ChangeScope(touched=frozenset({"drain"}))

        assert _rules("Call `drain(worker)`.", index=index, scope=scope) == ["SIGNATURE_MISMATCH"]


class TestAMethodNameThatTwoClassesShare:
    """Self-review 28, S-02.

    Level 28 widened the scope check so a diff's **bare** `render` covers a
    document's **qualified** `Renderer.render` — without which no method's
    signature had ever been checked. The widening was defended on the grounds
    that a name belonging to something else would fail to resolve.

    It resolves whenever two classes share a method name, which for `render`,
    `run`, `close` and `read` is the ordinary case rather than the exotic one.
    The change then proves nothing about the other class, and the tier reports a
    stale signature on a symbol nobody touched — the false-positive species this
    whole tier's scope discipline exists to prevent.
    """

    TWO_RENDERERS = SymbolIndex(
        names=frozenset({"render", "Renderer", "Legacy", "Renderer.render", "Legacy.render"}),
        signatures={
            "Renderer.render": ("self", "width", "height"),
            "Legacy.render": ("self", "a", "b"),
        },
    )
    ONE_RENDERER = SymbolIndex(
        names=frozenset({"render", "Renderer", "Renderer.render"}),
        signatures={"Renderer.render": ("self", "width", "height")},
    )
    TOUCHED = ChangeScope(touched=frozenset({"render"}))

    def test_the_other_class_is_not_the_one_the_change_touched(self):
        assert _rules("Call `Legacy.render(a)`.", index=self.TWO_RENDERERS, scope=self.TOUCHED) == []

    def test_neither_is_the_one_the_change_touched_when_both_are_documented(self):
        """The diff names `render`; which class it belongs to is not in it."""
        assert (
            _rules(
                "Call `Renderer.render(width)` or `Legacy.render(a)`.",
                index=self.TWO_RENDERERS,
                scope=self.TOUCHED,
            )
            == []
        )

    def test_the_only_method_with_that_name_is_still_checked(self):
        """Level 28's gap stays closed: one owner is not an ambiguity."""
        assert _rules("Call `Renderer.render(width)`.", index=self.ONE_RENDERER, scope=self.TOUCHED) == [
            "SIGNATURE_MISMATCH"
        ]

    def test_a_qualified_name_the_diff_names_in_full_is_always_checked(self):
        """No ambiguity to resolve: the change said which one."""
        scope = ChangeScope(touched=frozenset({"Legacy.render"}))

        assert _rules("Call `Legacy.render(a)`.", index=self.TWO_RENDERERS, scope=scope) == [
            "SIGNATURE_MISMATCH"
        ]
