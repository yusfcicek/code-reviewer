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

import ast
import logging
import re
from collections.abc import Callable, Mapping, Sequence

from .finding import Finding
from .remediation import Suggestion, SuggestionEdit

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


_INSECURE_RANDOM = re.compile(r"\brandom\.(random|randint|choice|randrange|shuffle|uniform)\(")
_HTTP_LITERAL = re.compile(r"""(?P<quote>['"])http://(?P<rest>[^'"]*)(?P=quote)""")
_LOOPBACK = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\])(?:[:/]|$)")
#: A bare `except:` with nothing after it on the line. The trailing `$` is the
#: whole of self-review S-01: without it, `except: raise` matched, the
#: replacement discarded everything after the colon, and a handler that
#: re-raised silently began swallowing.
_BARE_EXCEPT = re.compile(r"^(?P<indent>\s*)except\s*:\s*$")


def _is_commented_out(line: str, position: int) -> bool:
    """Whether the match at ``position`` sits inside a comment or a string.

    Crude on purpose — counting quotes before the match and looking for a `#`
    that is not itself quoted. A recipe needs to know *this line is not code*,
    which is a much smaller question than parsing it, and the answer is only
    used to decline (self-review 26, S-04).
    """
    prefix = line[:position]
    if prefix.count("'") % 2 or prefix.count('"') % 2:
        return True
    marker = prefix.find("#")
    return marker != -1


def _random_to_secrets(finding: Finding, lines: Sequence[str]) -> tuple[str, ...] | None:
    """`random.random()` → `secrets.SystemRandom().random()`.

    The recipe the multi-edit format exists for: it also needs `import secrets`,
    which :data:`REQUIRED_IMPORTS` arranges. `random` is not a weak generator
    for every purpose — it is a wrong one for anything a person must not
    predict, which is what the finding is about.
    """
    line = lines[finding.line_number - 1]
    match = _INSECURE_RANDOM.search(line)
    if match is None or _is_commented_out(line, match.start()):
        return None
    return (line[: match.start()] + f"secrets.SystemRandom().{match.group(1)}(" + line[match.end() :],)


def _http_to_https(finding: Finding, lines: Sequence[str]) -> tuple[str, ...] | None:
    """`"http://…"` → `"https://…"`, in a string literal only.

    A URL assembled from a variable is declined: upgrading a scheme this cannot
    see is a guess, and a guess that breaks a call to an internal service is a
    button nobody presses twice. A loopback address is declined too — plain
    HTTP to localhost is not the defect the rule is about, and rewriting one
    breaks a development setup for nothing.
    """
    line = lines[finding.line_number - 1]
    matches = list(_HTTP_LITERAL.finditer(line))
    if not matches:
        return None

    # Every URL on the line, or none. `search` upgraded the first and left the
    # second, which is half a fix a reviewer reads as a whole one — and the half
    # left behind is the one nobody looks at again, because the finding is now
    # closed (self-review 26, S-03).
    if any(_LOOPBACK.match(match.group("rest")) for match in matches):
        return None

    rewritten = _HTTP_LITERAL.sub(
        lambda m: f"{m.group('quote')}https://{m.group('rest')}{m.group('quote')}", line
    )
    return (rewritten,)


def _name_the_exception(finding: Finding, lines: Sequence[str]) -> tuple[str, ...] | None:
    """`except:` → `except Exception:`.

    Declines a handler whose body is a bare `raise`: that is a deliberate
    re-raise, and naming the exception changes what it catches — including
    `KeyboardInterrupt`, which is the whole reason the bare form is sometimes
    written on purpose.
    """
    line = lines[finding.line_number - 1]
    match = _BARE_EXCEPT.match(line)
    if match is None:
        return None

    for following in lines[finding.line_number : finding.line_number + 3]:
        if following.strip() == "raise":
            return None
        if following.strip() and not following.startswith(match.group("indent") + " "):
            break

    return (f"{match.group('indent')}except Exception:",)


#: Rule id to recipe. One recipe per rule at most: two recipes for one finding
#: would be two buttons doing different things to the same line.
RECIPES: Mapping[str, Recipe] = {
    "SAST.WEAK_CRYPTO": _md5_to_sha256,
    "SAST.INSECURE_DESERIALIZATION": _yaml_load_to_safe_load,
    "SAST.HARDCODED_SECRET": _secret_to_environment,
    "SAST.INSECURE_RANDOM": _random_to_secrets,
    "SAST.INSECURE_HTTP": _http_to_https,
    "QUALITY.ERROR_HANDLING": _name_the_exception,
}

#: Rules with no recipe, and why — the half of coverage that is a judgement.
#:
#: Level 25 made the argument this exists for: a coverage claim nobody can check
#: is a coverage claim. "We ship seven recipes" is a number somebody counts by
#: hand unless the ones without are named, and *declined* with no reason reads
#: as *forgotten*.
#:
#: Two kinds of entry. Most are declined because the fix is a **decision**, and
#: a recipe that guesses a decision produces a button that breaks a build. One
#: — `SAST.DEBUG_CODE` — is declined because its fix is a deletion, and Level 22
#: refused an empty replacement for a stated reason that this level honours
#: rather than reverses in passing.
DECLINED: Mapping[str, str] = {
    "SAST.INSECURE_FILE_OPERATION": (
        "the rule never reports the shape a recipe could fix: it fires on chmod(...777) and on "
        "open(..., 'w'), and the first needs a permission somebody chooses while the second needs "
        "path validation. A recipe written from the rule's name rather than its patterns is "
        "self-review 26, S-02"
    ),
    "SAST.DEBUG_CODE": (
        "the fix is a deletion, and Level 22 refused an empty replacement: deleting code is a "
        "change worth writing by hand"
    ),
    "SAST.SQL_INJECTION": (
        "parameterising a query means knowing which values are data, which is a reading of the "
        "code rather than a substitution in it"
    ),
    "SAST.COMMAND_INJECTION": "the safe form depends on what the command is for; no one-line rewrite exists",
    "SAST.PATH_TRAVERSAL": "the correct root to confine to is a decision about the deployment",
    "SAST.MISSING_INPUT_VALIDATION": "what counts as valid is the thing the code has not said",
    "SAST.SENSITIVE_DATA_EXPOSURE": "what is sensitive is a judgement about the data, not the syntax",
    "SAST.XSS": "the right escaping depends on the context the value lands in",
    "QUALITY.CODE_SMELL": "a smell names a shape; the fix is a rewrite somebody chooses",
    "QUALITY.DRY": "extracting the duplicate needs a name and a home, both decisions",
    "QUALITY.MAINTAINABILITY": "the fix is an extraction, and where to cut is the judgement",
    "QUALITY.TESTABILITY": "the fix is an injection point, which changes an interface",
    "QUALITY.SOLID_SRP": "splitting a class is a design decision; a recipe guessing one is wrong loudly",
    "QUALITY.SOLID_OCP": "the extension point is a design decision",
    "QUALITY.SOLID_LSP": "the fix is to the hierarchy, not to a line",
    "QUALITY.SOLID_ISP": "which interface to split, and where, is a decision",
    "QUALITY.SOLID_DIP": "the abstraction to depend on does not exist yet",
    "PERFORMANCE.N_PLUS_ONE": "the batched form depends on the data access layer",
    "PERFORMANCE.INEFFICIENT_LOOP": "the faster shape depends on what the loop is for",
    "PERFORMANCE.HIGH_COMPLEXITY": "the fix is an extraction, and where to cut is the judgement",
    "PERFORMANCE.BLOCKING_OPERATION": "making a call asynchronous changes every caller",
    "PERFORMANCE.MEMORY_LEAK": "the fix is to a lifetime, which is not on one line",
    "PERFORMANCE.RESOURCE_LEAK": "a context manager changes the block's shape, not one line in it",
    "PERFORMANCE.LARGE_MEMORY": "streaming instead of loading is a redesign of the function",
    "PERFORMANCE.RECURSIVE_RISK": "converting recursion to iteration is a rewrite",
    "PERFORMANCE.UNNECESSARY_COPY": "whether the copy is necessary is what the analyzer guessed at",
    "SEMANTIC.BREAKING": "a breaking change is a fact about the change, not a defect with a fix",
    "SEMANTIC.BUGFIX": "not a defect",
    "SEMANTIC.DOCS": "not a defect",
    "SEMANTIC.FEATURE": "not a defect",
    "SEMANTIC.REFACTOR": "not a defect",
    "SEMANTIC.STYLE": "not a defect",
    "SEMANTIC.UNKNOWN": "not a defect",
}

#: Recipes whose edit needs a module the file may not import yet. The second
#: edit is produced by :func:`import_edit`, which declines when the import is
#: already there — Level 26's reason for a suggestion being a *set*.
REQUIRED_IMPORTS: Mapping[str, str] = {
    "SAST.INSECURE_RANDOM": "secrets",
}

#: What each recipe is called, for the record and for the reader. Kept beside
#: the registry rather than inside each function, so the two cannot disagree.
RECIPE_NAMES: Mapping[str, str] = {
    "SAST.WEAK_CRYPTO": "md5-to-sha256",
    "SAST.INSECURE_DESERIALIZATION": "yaml-load-to-safe-load",
    "SAST.HARDCODED_SECRET": "secret-to-environment",
    "SAST.INSECURE_RANDOM": "random-to-secrets",
    "SAST.INSECURE_HTTP": "http-to-https",
    "QUALITY.ERROR_HANDLING": "name-the-exception",
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

    edits = [SuggestionEdit(finding.line_number, finding.line_number, tuple(replacement))]

    module = REQUIRED_IMPORTS.get(finding.rule_id)
    if module is not None:
        companion = import_edit(source, module)
        # `None` means the import is already there, which is not a failure: the
        # call still needs rewriting and the file already has what it needs.
        if companion is not None and not any(companion.overlaps(edit) for edit in edits):
            edits.append(companion)

    try:
        return Suggestion(
            rule_id=finding.rule_id,
            file_path=finding.file_path,
            edits=tuple(edits),
            recipe=RECIPE_NAMES.get(finding.rule_id, "unnamed"),
        )
    except ValueError as refusal:
        logger.warning(
            "A fix recipe produced something that is not a suggestion",
            extra={"fields": {"rule_id": finding.rule_id, "reason": str(refusal)}},
        )
        return None


def imports_module(source: str, module: str) -> bool:
    """Whether the file already imports ``module``, in any spelling.

    `import x`, `from x import y`, `import x as z`, `import x.y`. A recipe that
    added a second import of something already imported would produce a
    suggestion whose only effect is noise, and a reviewer who applies one of
    those stops applying them.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module or alias.name.startswith(f"{module}.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and (node.module or "") == module:
            return True
    return False


def import_edit(source: str, module: str) -> "SuggestionEdit | None":
    """An edit adding ``import module`` where imports belong, or ``None``.

    Expressed as a replacement of the line the import follows, because an edit
    replaces a range and an empty replacement is refused. That is what the edit
    means rather than a workaround: *the import goes after this line*.

    Three placements, in order of preference: after the last existing import,
    after the module docstring, at the top. Never before a docstring — a
    docstring that is no longer the first statement is no longer a docstring.

    ``None`` when the module is already imported, when the file will not parse,
    or when there is no file. A guess about where imports go in a file nobody
    can parse is a guess.
    """
    if not source.strip() or imports_module(source, module):
        return None

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    statement = f"import {module}"
    anchor = _last_import_line(tree) or _docstring_end_line(tree)

    if anchor is None:
        first = source.splitlines()[0]
        return SuggestionEdit(1, 1, (statement, first))

    lines = source.splitlines()
    return SuggestionEdit(anchor, anchor, (lines[anchor - 1], statement))


def _last_import_line(tree: ast.Module) -> int | None:
    """The line the last module-level import ends on."""
    lines = [
        node.end_lineno or node.lineno for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    return max(lines) if lines else None


def _docstring_end_line(tree: ast.Module) -> int | None:
    """The line a module docstring ends on, if there is one."""
    if not tree.body:
        return None
    first = tree.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first.end_lineno or first.lineno
    return None
