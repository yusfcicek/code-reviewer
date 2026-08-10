"""What a run is evidence of, against a catalogue somebody else wrote.

Level 24. [Level 20](../../docs/roadmap/level-20/spec.md) refused to build a
compliance framework and was right about the thing it named: an organisation's
obligations are an organisation's, and guessing at them here would be worse than
silence. It was not right about the **mapping**. An auditor asking *"show me
that changes are reviewed for injection flaws"* is otherwise handed rule ids and
left to derive the answer from source code — once per organisation, by hand.

So one named, versioned, publicly documented catalogue ships as **data**, and
this module reads it. Two properties follow, and both are tested rather than
promised:

**It claims coverage, never compliance.** That a finding exists under a control
means this system produced evidence relevant to it. Whether the control is met,
whether it is the right control, and whether the catalogue is the one an
organisation is held to are questions this repository cannot answer. A test
asserts the rendered output never contains "compliant" or "certified" — that
overclaim would be the documentation defect Level 23 exists to catch, in the one
place where it would be expensive.

**A control with no evidence is reported, not omitted.** Listing only what was
covered is how a report implies coverage it does not have, and "nothing in this
run speaks to SA-5" is the sentence an auditor is actually asking for.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from code_reviewer.domain.finding import Finding
from code_reviewer.errors import ConfigurationError

logger = logging.getLogger(__name__)

#: The catalogue shipped with this repository. Data, and replaceable.
DEFAULT_CATALOGUE = Path(__file__).resolve().parent.parent / "infrastructure" / "config" / "controls.yaml"


class CatalogueError(ConfigurationError):
    """A catalogue that could not be read.

    Refused rather than treated as empty: an empty mapping renders as "no
    control has evidence", which is a much more alarming and much less true
    statement than "the file is missing".
    """


@dataclass(frozen=True)
class ControlCatalogue:
    """A set of controls, and which rule namespaces speak to each.

    Names its own version and publisher because a control identifier means
    nothing without them — `SA-11` is a different control in a different
    revision, and a report that omits which one is a report an auditor has to
    come back and ask about.
    """

    name: str
    version: str
    publisher: str
    reference: str
    #: Namespace to the controls it is evidence for.
    mapping: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Control identifier to what it says.
    descriptions: Mapping[str, str] = field(default_factory=dict)

    def controls_for(self, namespace: str) -> tuple[str, ...]:
        return self.mapping.get(namespace.upper(), ())

    def describe(self, control: str) -> str:
        return self.descriptions.get(control, "")

    @property
    def controls(self) -> tuple[str, ...]:
        return tuple(sorted(self.descriptions))


@dataclass(frozen=True)
class ControlCoverage:
    """One control, and how much of this run speaks to it."""

    control: str
    description: str
    #: How many findings mapped here. Never which ones: coverage is about
    #: controls, and a path belongs in the review.
    findings: int = 0


@dataclass(frozen=True)
class CoverageReport:
    """What this run is evidence of, and what it is silent about."""

    catalogue: ControlCatalogue
    evidenced: tuple[ControlCoverage, ...] = ()
    unevidenced: tuple[ControlCoverage, ...] = ()
    #: Namespaces this run produced that the catalogue does not map. Reported
    #: rather than dropped: a namespace must not leave the report by being new.
    unmapped: tuple[str, ...] = ()


def load_catalogue(path: str | Path = DEFAULT_CATALOGUE) -> ControlCatalogue:
    """Reads a catalogue file. Refuses anything it cannot read completely."""
    target = Path(path)
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise CatalogueError(
            f"Could not read the control catalogue at '{target}': {type(error).__name__}"
        ) from error

    if not isinstance(raw, Mapping):
        raise CatalogueError(f"The control catalogue at '{target}' is not a mapping.")

    for required in ("name", "version", "publisher", "reference"):
        if not raw.get(required):
            raise CatalogueError(
                f"The control catalogue at '{target}' does not state its {required}. "
                "A control identifier means nothing without the catalogue and revision it is from."
            )

    mapping: dict[str, list[str]] = {}
    descriptions: dict[str, str] = {}
    for control, body in (raw.get("controls") or {}).items():
        if not isinstance(body, Mapping):
            raise CatalogueError(f"Control '{control}' is not a mapping.")
        descriptions[str(control)] = str(body.get("description", "")).strip()
        for namespace in body.get("namespaces") or []:
            mapping.setdefault(str(namespace).upper(), []).append(str(control))

    return ControlCatalogue(
        name=str(raw["name"]),
        version=str(raw["version"]),
        publisher=str(raw["publisher"]),
        reference=str(raw["reference"]),
        mapping={namespace: tuple(controls) for namespace, controls in mapping.items()},
        descriptions=descriptions,
    )


def coverage(catalogue: ControlCatalogue, findings: Sequence[Finding]) -> CoverageReport:
    """Which controls this run produced evidence for, and which it did not."""
    counts: dict[str, int] = dict.fromkeys(catalogue.controls, 0)
    unmapped: set[str] = set()

    for finding in findings:
        namespace = finding.namespace or finding.rule_id
        controls = catalogue.controls_for(namespace)
        if not controls:
            unmapped.add(namespace or "(no rule id)")
            continue
        for control in controls:
            counts[control] = counts.get(control, 0) + 1

    evidenced = tuple(
        ControlCoverage(control, catalogue.describe(control), count)
        for control, count in sorted(counts.items())
        if count
    )
    unevidenced = tuple(
        ControlCoverage(control, catalogue.describe(control))
        for control, count in sorted(counts.items())
        if not count
    )
    return CoverageReport(catalogue, evidenced, unevidenced, tuple(sorted(unmapped)))


def render_coverage(report: CoverageReport) -> str:
    """The coverage as markdown.

    Every sentence here is about *evidence*. Nothing says the organisation has
    met a control, because nothing here knows what meeting it requires.
    """
    catalogue = report.catalogue
    lines = [
        "# Control coverage\n",
        f"Against **{catalogue.name}**, {catalogue.version}, published by "
        f"{catalogue.publisher} ([reference]({catalogue.reference})).\n",
        "This states what this run produced **evidence relevant to**. It does not state "
        "that any control is met: that depends on obligations this tool does not know.\n",
    ]

    if report.evidenced:
        lines.append("\n## Controls with evidence in this run\n")
        lines.append("| control | findings | what it covers |")
        lines.append("|---|---:|---|")
        lines.extend(
            f"| `{entry.control}` | {entry.findings} | {entry.description} |" for entry in report.evidenced
        )

    if report.unevidenced:
        lines.append("\n## Controls with no evidence in this run\n")
        lines.append(
            "Nothing here speaks to these. That is a fact about this run, not a "
            "judgement about the control.\n"
        )
        lines.extend(f"- `{entry.control}` — {entry.description}" for entry in report.unevidenced)

    if report.unmapped:
        lines.append("\n## Findings this catalogue does not map\n")
        lines.extend(f"- `{namespace}`" for namespace in report.unmapped)
        lines.append("\nAdd them to the catalogue, or accept that they are evidence of nothing in it.\n")

    return "\n".join(lines) + "\n"
