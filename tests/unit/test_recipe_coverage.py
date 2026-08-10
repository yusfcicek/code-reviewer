"""Step 4 — recipe coverage, measured rather than asserted.

"We ship three recipes" was a number somebody had to count by hand, and Level 25
made the argument for why that is not good enough: a coverage claim nobody can
check is a coverage claim.

The shape is the one Level 20 used for the attribution table and Level 24 for
the control catalogue. Every rule the analyzers can emit is either mapped to a
recipe or carries a **recorded reason** for not having one. A new rule with
neither is a red test rather than a silent omission.
"""

from code_reviewer.application.recipe_coverage import recipe_coverage, render_recipe_coverage
from code_reviewer.domain.fix_recipes import DECLINED, RECIPES
from code_reviewer.infrastructure.analyzers.rules import emittable_rules


class TestWhatTheSuiteCanEmit:
    def test_the_emittable_set_covers_every_analyzer(self):
        namespaces = {rule.partition(".")[0] for rule in emittable_rules()}

        assert namespaces == {"SAST", "QUALITY", "PERFORMANCE", "SEMANTIC"}

    def test_it_is_derived_from_the_analyzers_rather_than_listed(self):
        """A hand-written list is a list that drifts. This one comes from the
        same enums the suite turns into rule ids."""
        assert "SAST.SQL_INJECTION" in emittable_rules()
        assert "QUALITY.SOLID_SRP" in emittable_rules()

    def test_there_are_more_rules_than_recipes(self):
        """The fact the report exists to state."""
        assert len(emittable_rules()) > len(RECIPES)


class TestCompleteness:
    def test_every_rule_has_a_recipe_or_a_recorded_reason(self):
        """The completeness test. A new rule with neither is red rather than
        quietly uncovered."""
        unaccounted = [rule for rule in emittable_rules() if rule not in RECIPES and rule not in DECLINED]

        assert unaccounted == [], unaccounted

    def test_no_rule_is_both_recipe_and_declined(self):
        assert set(RECIPES) & set(DECLINED) == set()

    def test_every_declined_rule_states_why(self):
        """AC-16. 'Declined' with no reason reads as 'forgotten'."""
        for rule, reason in DECLINED.items():
            assert reason.strip(), rule

    def test_every_recipe_names_a_rule_that_can_be_emitted(self):
        """A recipe for a rule nobody produces is dead code reading as a feature."""
        for rule in RECIPES:
            assert rule in emittable_rules(), rule


class TestTheCoverageFigure:
    def test_it_counts_what_has_a_recipe(self):
        coverage = recipe_coverage(emittable_rules())

        assert coverage.with_recipe == len(RECIPES)

    def test_it_counts_what_the_analyzers_can_emit(self):
        coverage = recipe_coverage(emittable_rules())

        assert coverage.emittable == len(emittable_rules())

    def test_it_names_the_rules_without_one(self):
        """AC-15."""
        coverage = recipe_coverage(emittable_rules())

        assert "QUALITY.SOLID_SRP" in coverage.without_recipe

    def test_the_share_is_a_share(self):
        assert 0.0 < recipe_coverage(emittable_rules()).share < 1.0


class TestTheRendering:
    def test_it_states_the_count_and_the_total(self):
        text = render_recipe_coverage(recipe_coverage(emittable_rules()))

        assert str(len(RECIPES)) in text
        assert str(len(emittable_rules())) in text

    def test_it_names_a_declined_rule_and_its_reason(self):
        text = render_recipe_coverage(recipe_coverage(emittable_rules()))

        assert "SAST.DEBUG_CODE" in text
        assert "deletion" in text.lower()

    def test_it_never_claims_the_coverage_is_sufficient(self):
        """The same rule Level 25 put on the evaluation report."""
        text = render_recipe_coverage(recipe_coverage(emittable_rules())).lower()

        for word in ("sufficient", "complete coverage", "comprehensive"):
            assert word not in text

    def test_a_rule_with_neither_is_rendered_as_unaccounted(self):
        """The state the completeness test forbids, rendered anyway — so that a
        run against a modified analyzer set says something useful."""
        coverage = recipe_coverage(("SAST.SQL_INJECTION", "MADE.UP_RULE"))

        assert "MADE.UP_RULE" in render_recipe_coverage(coverage)
