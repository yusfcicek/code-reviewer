"""Three deterministic edits, and everything they decline.

In the domain rather than beside the analyzers, and the reason is the one
`gate.py` gives: a recipe is a rule about code that needs no filesystem, no
model and no network. Every edge case in it is settled by a regular expression
over a line somebody already read.

A recipe reads the line a finding names and either produces the replacement for
it or produces nothing. There is no third answer: no partial edit, no best
guess, no "probably". That refusal is the level — a recipe that guesses produces
a button that breaks a build, and one broken button costs every future
suggestion its credibility (contract C-4).

Each recipe works on the line the finding claimed, never on the file. A recipe
that searched for its own pattern would edit a line the finding said nothing
about, and the reader would have no way to connect the two.
"""

import logging
import re
from collections.abc import Callable, Mapping, Sequence

from .finding import Finding
from .remediation import Suggestion

logger = logging.getLogger(__name__)

#: A recipe: the finding, the file's lines, and the replacement lines it
#: proposes for the finding's line — or ``None``.
Recipe = Callable[[Finding, Sequence[str]], tuple[str, ...] | None]

_WEAK_DIGEST = re.compile(r"\bhashlib\.(?:md5|sha1)\s*\(")
_YAML_LOAD = re.compile(r"\byaml\.load\s*\((?![^)]*Loader\s*=)")
#: An assignment of a string literal to a name. The name has to look like a
#: constant, because `path = "/tmp/x"` is not a credential and rewriting it
#: would be a recipe inventing a problem.
_SECRET_ASSIGNMENT = re.compile(
    r"^(?P<indent>\s*)(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*(?P<quote>['\"]).*(?P=quote)\s*$"
)


def _md5_to_sha256(finding: Finding, lines: Sequence[str]) -> tuple[str, ...] | None:
    """`hashlib.md5(` → `hashlib.sha256(`.

    Behaviour changes on purpose: that is what the finding is about. What is
    not claimed is that the program means the same thing afterwards — a stored
    digest computed with MD5 will not match one computed with SHA-256, and the
    remediation text says so.
    """
    line = lines[finding.line_number - 1]
    if not _WEAK_DIGEST.search(line):
        return None
    return (_WEAK_DIGEST.sub("hashlib.sha256(", line),)


def _yaml_load_to_safe_load(finding: Finding, lines: Sequence[str]) -> tuple[str, ...] | None:
    """`yaml.load(` → `yaml.safe_load(`, and nothing else under this rule.

    The same rule id also covers `pickle.loads` and `marshal.loads`, for which
    there is no one-line change that makes them safe on untrusted data.
    Declining is the honest answer there.
    """
    line = lines[finding.line_number - 1]
    if not _YAML_LOAD.search(line):
        return None
    return (_YAML_LOAD.sub("yaml.safe_load(", line),)


def _secret_to_environment(finding: Finding, lines: Sequence[str]) -> tuple[str, ...] | None:
    """A literal assigned to a constant → the same name read from the environment.

    Declines when the file does not already import `os`: a suggestion that
    leaves the file failing to import is a suggestion that wastes somebody's
    afternoon, and adding the import is a second hunk this level does not do.

    The replacement never carries the literal. Not for tidiness — the comment
    it goes into is read by more people than the diff.
    """
    line = lines[finding.line_number - 1]
    match = _SECRET_ASSIGNMENT.match(line)
    if match is None:
        return None
    if not any(re.match(r"\s*(?:import\s+os\b|from\s+os\s+import\b)", other) for other in lines):
        return None

    name = match.group("name")
    return (f'{match.group("indent")}{name} = os.environ["{name}"]',)


#: Rule id to recipe. One recipe per rule at most: two edits for one finding
#: would be two buttons doing different things to the same line.
RECIPES: Mapping[str, Recipe] = {
    "SAST.WEAK_CRYPTO": _md5_to_sha256,
    "SAST.INSECURE_DESERIALIZATION": _yaml_load_to_safe_load,
    "SAST.HARDCODED_SECRET": _secret_to_environment,
}

#: What each recipe is called, for the record and for the reader. Kept beside
#: the registry rather than inside each function, so the two cannot disagree.
RECIPE_NAMES: Mapping[str, str] = {
    "SAST.WEAK_CRYPTO": "md5-to-sha256",
    "SAST.INSECURE_DESERIALIZATION": "yaml-load-to-safe-load",
    "SAST.HARDCODED_SECRET": "secret-to-environment",
}


def recipe_for(rule_id: str) -> Recipe | None:
    """The recipe for a rule, or ``None`` where there is not one."""
    return RECIPES.get(rule_id)


def suggest(finding: Finding, source: str) -> Suggestion | None:
    """A suggestion for one finding, or ``None``.

    Never raises. A recipe that throws costs its own suggestion and nothing
    else: the review has already been paid for, and losing it to a regex is
    not a trade this project makes.
    """
    recipe = recipe_for(finding.rule_id)
    if recipe is None or not source:
        return None

    lines = source.splitlines()
    if not 1 <= finding.line_number <= len(lines):
        return None

    try:
        replacement = recipe(finding, lines)
    except Exception as error:  # a recipe is a regex; a regex is a place to be wrong
        logger.warning(
            "A fix recipe failed; the finding keeps its written advice",
            extra={"fields": {"rule_id": finding.rule_id, "error": str(error)}},
        )
        return None

    if not replacement or list(replacement) == lines[finding.line_number - 1 : finding.line_number]:
        # An edit that changes nothing is noise in a merge request.
        return None

    try:
        return Suggestion(
            rule_id=finding.rule_id,
            file_path=finding.file_path,
            start_line=finding.line_number,
            end_line=finding.line_number,
            replacement=tuple(replacement),
            recipe=RECIPE_NAMES.get(finding.rule_id, "unnamed"),
        )
    except ValueError as refusal:
        logger.warning(
            "A fix recipe produced something that is not a suggestion",
            extra={"fields": {"rule_id": finding.rule_id, "reason": str(refusal)}},
        )
        return None
