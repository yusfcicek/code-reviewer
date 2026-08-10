"""How much of what the analyzers report can be offered as a fix.

Level 26. "We ship three recipes" was a number somebody had to count by hand,
and Level 25 made the argument for why that is not enough: a coverage claim
nobody can check is a coverage claim.

The shape is the one Level 20 used for the attribution table and Level 24 for
the control catalogue. Every rule the analyzers can emit is either mapped to a
recipe or carries a recorded reason for not having one, and a rule with neither
is a red test rather than a silent gap.

Three layers, each holding what it is about. Which rules exist is a fact about
this deployment's analyzers and is enumerated in
`infrastructure/analyzers/rules.py`. Which of them deserve a recipe is a
judgement and lives in `domain/fix_recipes.py`, beside the recipes. Putting the
two together is this module, and it imports neither analyzer.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from code_reviewer.domain.fix_recipes import DECLINED, RECIPES


@dataclass(frozen=True)
class RecipeCoverage:
    """What has a fix, what does not, and what nobody has decided about."""

    emittable: int = 0
    with_recipe: int = 0
    without_recipe: tuple[str, ...] = ()
    declined: Mapping[str, str] = field(default_factory=dict)
    #: Rules with neither a recipe nor a reason. The completeness test forbids
    #: this; it is rendered anyway, so a run against a modified analyzer set
    #: says something useful rather than nothing.
    unaccounted: tuple[str, ...] = ()

    @property
    def share(self) -> float:
        return self.with_recipe / self.emittable if self.emittable else 0.0


def recipe_coverage(rules: Sequence[str]) -> RecipeCoverage:
    """The coverage figure over the rules a deployment's analyzers can emit.

    The rules are passed in rather than imported: enumerating them reads the
    analyzers, and this layer does not (the architecture test said so before a
    human did, for the third time in this roadmap).
    """
    considered = tuple(rules)
    without = tuple(rule for rule in considered if rule not in RECIPES)
    return RecipeCoverage(
        emittable=len(considered),
        with_recipe=sum(1 for rule in considered if rule in RECIPES),
        without_recipe=without,
        declined={rule: DECLINED[rule] for rule in without if rule in DECLINED},
        unaccounted=tuple(rule for rule in without if rule not in DECLINED),
    )


def render_recipe_coverage(coverage: RecipeCoverage) -> str:
    """The coverage as markdown.

    States the number and names the gaps. It does not say the coverage is
    sufficient — what is worth having a recipe for is a judgement, and the
    reasons beside each declined rule are where that judgement is written down.
    """
    lines = [
        "# Fix recipe coverage",
        "",
        f"**{coverage.with_recipe} of {coverage.emittable}** rule id(s) the analyzers can emit "
        f"have a deterministic fix recipe ({coverage.share:.0%}).",
        "",
        "A rule without one produces the written advice it always did. The reasons below are "
        "the judgement, written where it can be argued with.",
        "",
    ]

    if coverage.declined:
        lines += ["## Declined, and why", "", "| rule | reason |", "|---|---|"]
        lines += [f"| `{rule}` | {reason} |" for rule, reason in sorted(coverage.declined.items())]
        lines.append("")

    if coverage.unaccounted:
        lines += [
            "## Neither a recipe nor a reason",
            "",
            "These are new since somebody last looked, and a rule in this list is a rule "
            "nobody has decided about:",
            "",
        ]
        lines += [f"- `{rule}`" for rule in coverage.unaccounted]
        lines.append("")

    return "\n".join(lines)
