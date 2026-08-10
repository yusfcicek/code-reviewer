"""What a document claims, and whether the code offers it.

Level 23. The roadmap has said since Level 0 that documentation may never claim
behaviour the code does not have, and until now that was an agreement rather
than a check — the analysis suite reads Python and skips Markdown.

The reason it earns a level of its own: **prose outranks code in the reader's
head, and outranks it completely in a model's.** An agent answering a question
about this repository reads the README before it reads the module, and believes
the README. A stale sentence is therefore not a cosmetic defect; it is a wrong
answer served with confidence to everybody downstream, including the reviewer
of the next merge request.

Everything here is arithmetic over text, which is why it sits beside `gate.py`
and `fix_recipes.py` rather than in an adapter: no filesystem, no index, no
model. Building the index is I/O and lives in infrastructure; deciding what a
backtick means does not.

The precision argument is one function. This project's own README puts `async`,
`false`, `critical` and `auto` in backticks beside `AgentExecutor` and
`create_app`, so a rule that treats every span as a symbol reports the English
as dead code on its first run — and a namespace that does that once is a
namespace people mute. :func:`_symbol_shaped` is what stands between the two,
and it is deliberately conservative: a span it cannot classify produces no
claim, because a missed stale reference costs one defect and a false one costs
the reader's attention for every future finding.
"""

import ast
import re
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from .remediation import Suggestion


class ClaimKind(Enum):
    """What a piece of a document asserts about the code."""

    #: A name the code is expected to define.
    SYMBOL = "symbol"
    #: A call written with parameter names, which states a signature.
    SIGNATURE = "signature"
    #: A command-line option.
    OPTION = "option"
    #: A `SCREAMING_SNAKE` name — an environment variable or a constant.
    ENVIRONMENT = "environment"
    #: A fenced Python block, which claims to be code that runs.
    EXAMPLE = "example"


@dataclass(frozen=True)
class DocumentClaim:
    """One assertion a document makes, and where it makes it.

    Deliberately not carrying the sentence around it. Five levels have kept
    source text out of memory, traces, records and comments; this is the first
    where the quoted material would be prose a person wrote, and quoting
    somebody's paragraph back at them inside a machine's report is worse
    manners than quoting their code.
    """

    kind: ClaimKind
    #: The symbol, flag or variable named. Empty for an example.
    subject: str
    line: int
    #: Nearest preceding Markdown heading; empty when the document has none.
    heading: str = ""
    #: Argument names, for a signature claim.
    arguments: tuple[str, ...] = ()
    #: The block's source, for an example claim.
    source: str = ""


@dataclass(frozen=True)
class SymbolIndex:
    """What the source tree offers, as names.

    ``EMPTY`` is a real state rather than an error: a tree that would not parse,
    a workspace that refused a read, a run with no checkout. The rules check
    :attr:`is_empty` before they report anything, because an index that knows
    nothing would otherwise make every reference in every document look dead —
    the failure mode that would retire this namespace in one afternoon.
    """

    names: frozenset[str] = frozenset()
    signatures: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    options: frozenset[str] = frozenset()
    environment: frozenset[str] = frozenset()

    EMPTY: ClassVar["SymbolIndex"]

    @property
    def is_empty(self) -> bool:
        return not (self.names or self.options or self.environment)

    def resolves(self, name: str) -> bool:
        """True when the tree defines this name, bare or as a dotted path."""
        if self.is_empty or not name:
            return False
        return name in self.names or name.rsplit(".", 1)[-1] in self.names

    def parameters_of(self, name: str) -> tuple[str, ...] | None:
        """The symbol's parameter names, or ``None``.

        ``None`` covers both "not indexed" and "indexed but not a function".
        A caller that needs to tell those apart asks :meth:`resolves` too — and
        the signature rule does, because reporting a mismatch against a class
        would be reporting nonsense.
        """
        # Exact only, dotted or not. Falling back to the last segment made
        # `yaml.load` resolve to a `load` defined somewhere in this tree, and
        # the rule then reported a library's signature as this project's
        # mistake. A qualified symbol the tree indexed is stored qualified.
        return self.signatures.get(name)

    def knows_option(self, flag: str) -> bool:
        return flag in self.options

    def knows_environment(self, name: str) -> bool:
        """An uppercase name is an environment variable *or* a constant.

        A document naming `MAX_SUGGESTION_LINES` is naming a module constant,
        and nothing in the text distinguishes it from `CI_PROJECT_ID`. Both
        answers are accepted, because reporting the constant would be wrong and
        there is no evidence available to tell them apart.
        """
        return name in self.environment or self.resolves(name)


SymbolIndex.EMPTY = SymbolIndex()

#: A Markdown fence, with the language it declares.
_FENCE = re.compile(r"^\s*```(?P<language>[A-Za-z0-9_+-]*)\s*$")

#: An inline code span. Non-greedy so two spans on a line stay two spans.
_SPAN = re.compile(r"`([^`\n]+)`")

#: An ATX heading.
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(?P<title>.+?)\s*#*\s*$")

#: A command-line option: `--strict`, `--max-lines`.
_OPTION = re.compile(r"^--[A-Za-z][A-Za-z0-9-]*$")

#: `SCREAMING_SNAKE`, two segments or more. One segment is refused on purpose:
#: `DEBUG`, `FAIL` and `CRITICAL` appear in this repository's README as enum
#: values written as prose, and they are indistinguishable from a variable.
_SCREAMING = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")

#: A dotted or bare identifier.
_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")

#: A call: name, parentheses, whatever is between them.
_CALL = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\((?P<arguments>.*)\)$")

#: Lowercase-then-uppercase, which is what makes a name CamelCase rather than
#: an acronym. `AgentExecutor` matches; `DEBUG` deliberately does not.
_CAMEL = re.compile(r"^[A-Z][a-z0-9]+[A-Z]")

#: Fence languages read as runnable Python.
_PYTHON_FENCES = frozenset({"python", "py", "python3"})


def _symbol_shaped(token: str) -> bool:
    """Whether a bare token looks like a name the code would define.

    Three shapes qualify: dotted, snake_case, and CamelCase. A single lowercase
    word does not, and that is the rule doing its job — `async`, `auto` and
    `false` are English in this repository's README, and each of them is also a
    plausible identifier somewhere. Refusing the ambiguous case costs a real
    reference now and then; accepting it costs the namespace its credibility.
    """
    if not _DOTTED.match(token):
        return False
    return "." in token or "_" in token or bool(_CAMEL.match(token))


def _claim_from_span(
    token: str, line: int, heading: str, named: frozenset[str] = frozenset()
) -> DocumentClaim | None:
    """One inline code span, classified — or nothing, which is the common case.

    ``named`` overrides the shape test. A token the caller already knows to be
    one of the repository's names needs no guess about its shape, and guessing
    anyway was self-review finding S-02: the shape test threw away the diff's
    direct evidence and made 17 % of this project's functions unreportable.
    """
    token = token.strip()
    if not token:
        return None

    if _OPTION.match(token):
        return DocumentClaim(ClaimKind.OPTION, token, line, heading)

    if _SCREAMING.match(token):
        return DocumentClaim(ClaimKind.ENVIRONMENT, token, line, heading)

    call = _CALL.match(token)
    if call is not None:
        return _claim_from_call(call, line, heading)

    if _symbol_shaped(token) or token in named:
        return DocumentClaim(ClaimKind.SYMBOL, token, line, heading)
    return None


def _claim_from_call(call: "re.Match[str]", line: int, heading: str) -> DocumentClaim:
    """A written call, which states either a signature or just a name.

    `render(version, outcome)` names parameters and is a claim about the
    signature. `render("1.0", 2)` shows somebody how to call it and says
    nothing about parameter names — a document showing usage is not a document
    stating a signature, and grading it as one would report every example in
    every README.
    """
    name = call.group("name")
    raw = call.group("arguments").strip()
    if not raw:
        return DocumentClaim(ClaimKind.SYMBOL, name, line, heading)

    parts = [part.strip() for part in raw.split(",")]
    if all(_DOTTED.match(part) and "." not in part for part in parts):
        return DocumentClaim(ClaimKind.SIGNATURE, name, line, heading, arguments=tuple(parts))
    return DocumentClaim(ClaimKind.SYMBOL, name, line, heading)


def claims_in(text: str, named: frozenset[str] = frozenset()) -> list[DocumentClaim]:
    """Every claim a Markdown document makes, in document order.

    Args:
        text: The document.
        named: Names to accept as symbols whatever their shape — in practice,
            what the change removed or touched. Without it a document saying
            `` `drain` `` is unreadable even when the diff just deleted
            ``def drain(...)`` (self-review S-02).

    Never raises. A document is somebody's writing in a format with no schema,
    and the only responsible failure mode is to find fewer claims.
    """
    claims: list[DocumentClaim] = []
    heading = ""
    fence_language: str | None = None
    fence_start = 0
    fenced: list[str] = []

    for number, line in enumerate(text.splitlines(), start=1):
        fence = _FENCE.match(line)
        if fence is not None:
            if fence_language is None:
                fence_language, fence_start, fenced = fence.group("language").lower(), number, []
            else:
                if fence_language in _PYTHON_FENCES:
                    claims.append(
                        DocumentClaim(
                            ClaimKind.EXAMPLE,
                            "",
                            fence_start,
                            heading,
                            # Dedented: a fence inside a list item carries the
                            # list's indentation, and `ast.parse` calls that an
                            # IndentationError. This repository's own
                            # CONTRIBUTING.md has one, and it was the single
                            # false positive left in the first dry run.
                            source=textwrap.dedent("".join(f"{held}\n" for held in fenced)),
                        )
                    )
                fence_language = None
            continue

        if fence_language is not None:
            # Inside a fence. Backticks here are code, not spans.
            fenced.append(line)
            continue

        title = _HEADING.match(line)
        if title is not None:
            heading = title.group("title")
            continue

        for token in _SPAN.findall(line):
            claim = _claim_from_span(token, number, heading, named)
            if claim is not None:
                claims.append(claim)

    return claims


def parses(source: str) -> bool:
    """Whether a fenced block is syntactically Python."""
    try:
        ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    return True


#: Rule names, qualified by the suite into `DOCS.DEAD_REFERENCE` and friends.
DEAD_REFERENCE = "DEAD_REFERENCE"
SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"
UNKNOWN_OPTION = "UNKNOWN_OPTION"
BROKEN_EXAMPLE = "BROKEN_EXAMPLE"
DOCSTRING_DRIFT = "DOCSTRING_DRIFT"

#: The namespace the deterministic tier reports under. Repeated here rather
#: than imported from the application layer, which is the wrong direction.
NAMESPACE_DOCS = "DOCS"

#: Parameters a document is never expected to write.
_IMPLICIT = frozenset({"self", "cls"})


@dataclass(frozen=True)
class DocDefect:
    """One place a document and the code disagree.

    ``detail`` is built from identifiers — names, counts, rule ids — and never
    from the document's prose. The distinction is the same one Levels 14, 17,
    20 and 22 made about source text, and it matters more here: the material
    being quoted would be a sentence somebody wrote.
    """

    rule: str
    subject: str
    line: int
    heading: str = ""
    detail: str = ""


@dataclass(frozen=True)
class ChangeScope:
    """What this merge request changed, as names.

    The reason every rule takes one. A first cut of this module resolved every
    backtick in every document against the tree, and a dry run over this
    repository produced twenty-five findings in the README of which almost all
    were wrong: `yaml.safe_load` and `hashlib.md5` are real functions in
    libraries this tree does not define, `ConfigMap` is a Kubernetes noun,
    `--cov` is a pytest flag and `id_rsa` is a filename. Nothing in the text
    distinguishes those from a symbol this project once had and lost.

    The diff does. A name the change **removed** is a name the repository was
    responsible for, and a document still naming it is stale by proof rather
    than by resemblance. So the rules ask what changed, and say nothing about
    the rest — which is also what the level's own non-goals promised, before
    the first implementation quietly scanned everything.
    """

    #: Names the change deleted or renamed away.
    removed: frozenset[str] = frozenset()
    #: Names whose definition the change altered, removals included.
    touched: frozenset[str] = frozenset()
    #: Whether this document itself was edited in the change. When it was, its
    #: author is available to fix what is found, so the provable rules run over
    #: the whole document rather than only over what the code changed.
    document_changed: bool = False

    def merged_with(self, other: "ChangeScope") -> "ChangeScope":
        """The union. A merge request is many files, and one scope."""
        return ChangeScope(
            removed=self.removed | other.removed,
            touched=self.touched | other.touched,
            document_changed=self.document_changed or other.document_changed,
        )

    @property
    def names(self) -> frozenset[str]:
        """Everything the change is responsible for, whatever its shape.

        Handed to :func:`claims_in` so a document naming one of them is read as
        naming a symbol even when the token is a bare lowercase word — the diff
        has already answered the question the shape test guesses at.
        """
        return self.removed | self.touched

    def covers(self, subject: str) -> bool:
        """Whether the change is responsible for this name, dotted or not.

        A diff of a method yields the **bare** name — `def render(self, …)` is a
        line that declares `render` — while a document names it **qualified**,
        as `Renderer.render`. Comparing the two as strings missed every
        signature a method ever had, which is what Level 28's new case found on
        its first run.

        The final segment is enough because resolution is the second half of
        every rule: a document naming `SomethingElse.render` matches here and
        then resolves to nothing, so the scope widening cannot produce a claim
        the index does not back.
        """
        return subject in self.touched or subject.rsplit(".", 1)[-1] in self.touched

    def for_document(self, changed: bool) -> "ChangeScope":
        """The same scope, told whether *this* document was edited."""
        return ChangeScope(removed=self.removed, touched=self.touched, document_changed=changed)


#: What a line defines: a function, a class, or a module-level name.
_DEFINES = re.compile(
    r"^\s*(?:async\s+def|def|class)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|^(?P<constant>[A-Z][A-Z0-9_]*)\s*(?::[^=]+)?="
)

#: A quoted option or environment name on a line. Options and environment
#: variables only exist in the source as string literals, so this is the only
#: shape available.
_QUOTED = re.compile(r"[\"'](?P<value>--[A-Za-z][A-Za-z0-9-]*|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)[\"']")


def _names_on(line: str) -> set[str]:
    """Every name a single line of source defines or literally spells."""
    found: set[str] = set()
    definition = _DEFINES.match(line)
    if definition is not None:
        found.add(definition.group("name") or definition.group("constant"))
    found.update(match.group("value") for match in _QUOTED.finditer(line))
    return found


def scope_from_diff(diff: str, document_changed: bool = False) -> ChangeScope:
    """What a unified diff removed and what it touched.

    Removed means *gone*: a name on a deleted line and on no added line. That
    subtraction is what makes a rename report the old name and stay quiet about
    the new one, and what keeps a reordered block from looking like a deletion.

    The `---`/`+++` file headers are skipped explicitly. They begin with the
    same characters as content lines, and reading `--- a/app.py` as a deletion
    would put a path into the scope on every diff.
    """
    deleted: set[str] = set()
    added: set[str] = set()

    for line in diff.splitlines():
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("-"):
            deleted |= _names_on(line[1:])
        elif line.startswith("+"):
            added |= _names_on(line[1:])

    return ChangeScope(
        removed=frozenset(deleted - added),
        touched=frozenset(deleted | added),
        document_changed=document_changed,
    )


def documentation_defects(
    claims: "list[DocumentClaim]", index: SymbolIndex, scope: ChangeScope
) -> list[DocDefect]:
    """Every claim the change proves wrong, in document order.

    Two silences are deliberate. An empty index means nothing was read, and the
    honest answer to "does `create_app` exist" is *unknown* rather than *no* —
    without that, one shallow checkout reports every reference in every
    document. And a claim outside ``scope`` is not examined at all, however
    suspicious it looks: this level reports what a change made false, not what
    it can find wrong with somebody's prose.
    """
    defects: list[DocDefect] = []
    for claim in claims:
        defect = _defect_for(claim, index, scope)
        if defect is not None:
            defects.append(defect)
    return defects


def _defect_for(claim: DocumentClaim, index: SymbolIndex, scope: ChangeScope) -> DocDefect | None:
    if claim.kind is ClaimKind.EXAMPLE:
        if not scope.document_changed or parses(claim.source):
            return None
        return DocDefect(BROKEN_EXAMPLE, claim.subject, claim.line, claim.heading, "the block does not parse")

    if index.is_empty:
        return None

    if claim.kind in (ClaimKind.SYMBOL, ClaimKind.SIGNATURE):
        return _symbol_defect(claim, index, scope)

    if claim.subject not in scope.removed:
        return None

    if claim.kind is ClaimKind.OPTION and not index.knows_option(claim.subject):
        return DocDefect(UNKNOWN_OPTION, claim.subject, claim.line, claim.heading, "the change removed it")

    if claim.kind is ClaimKind.ENVIRONMENT and not index.knows_environment(claim.subject):
        return DocDefect(UNKNOWN_OPTION, claim.subject, claim.line, claim.heading, "the change removed it")

    return None


def _symbol_defect(claim: DocumentClaim, index: SymbolIndex, scope: ChangeScope) -> DocDefect | None:
    """A named symbol, and — when the document wrote one — its signature.

    A dead name produces one defect rather than two. The signature is
    unknowable until the name is, and reporting both would charge a reader
    twice for one mistake.
    """
    if claim.subject in scope.removed and not index.resolves(claim.subject):
        return DocDefect(DEAD_REFERENCE, claim.subject, claim.line, claim.heading, "the change removed it")

    if claim.kind is not ClaimKind.SIGNATURE:
        return None
    if not (scope.document_changed or scope.covers(claim.subject)):
        return None

    defined = index.parameters_of(claim.subject)
    if defined is None:
        # Not indexed, or indexed as something without parameters: a class, a
        # constant, a module, or a dotted name belonging to a library this tree
        # does not define. There is nothing to compare against.
        return None

    if tuple(claim.arguments) == defined:
        return None

    return DocDefect(
        SIGNATURE_MISMATCH,
        claim.subject,
        claim.line,
        claim.heading,
        f"documented ({', '.join(claim.arguments)}), defined ({', '.join(defined)})",
    )


#: `Args:` / `Returns:` / `Raises:`, and the Sphinx field spellings beside them.
#: Both appear in this repository, which is the ordinary state of a codebase
#: with more than one author.
_SECTION = re.compile(r"^\s*(?P<name>Args|Arguments|Parameters|Returns|Yields|Raises)\s*:\s*$")
_GOOGLE_ENTRY = re.compile(r"^\s*(?P<name>\*{0,2}[A-Za-z_][A-Za-z0-9_.]*)\s*(?:\([^)]*\))?\s*:")
_SPHINX_PARAM = re.compile(r"^\s*:param\s+(?:[^:]+\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:")
_SPHINX_RAISES = re.compile(r"^\s*:raises?\s+(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*:")
_SPHINX_RETURNS = re.compile(r"^\s*:returns?\s*:")


@dataclass(frozen=True)
class _Documented:
    """What a docstring says about a function, reduced to names."""

    parameters: tuple[str, ...] = ()
    raises: tuple[str, ...] = ()
    returns: bool = False


def _documented(docstring: str) -> _Documented:
    """Reads a docstring's sections. Never raises; an unrecognised shape is empty."""
    parameters: list[str] = []
    raises: list[str] = []
    returns = False
    section = ""

    for line in docstring.splitlines():
        heading = _SECTION.match(line)
        if heading is not None:
            section = heading.group("name").lower()
            if section in ("returns", "yields"):
                returns = True
            continue

        sphinx = _SPHINX_PARAM.match(line)
        if sphinx is not None:
            parameters.append(sphinx.group("name"))
            continue
        sphinx = _SPHINX_RAISES.match(line)
        if sphinx is not None:
            raises.append(sphinx.group("name"))
            continue
        if _SPHINX_RETURNS.match(line):
            returns = True
            continue

        if not line.strip():
            # A blank line ends a Google-style block. Without this, prose after
            # the section is read as more entries.
            section = ""
            continue

        entry = _GOOGLE_ENTRY.match(line)
        if entry is None:
            continue
        name = entry.group("name").lstrip("*")
        if section in ("args", "arguments", "parameters"):
            parameters.append(name)
        elif section == "raises":
            raises.append(name)

    return _Documented(tuple(parameters), tuple(raises), returns)


def _parameter_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    arguments = function.args
    named = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    names = [argument.arg for argument in named if argument.arg not in _IMPLICIT]
    if arguments.vararg:
        names.append(arguments.vararg.arg)
    if arguments.kwarg:
        names.append(arguments.kwarg.arg)
    return tuple(names)


def _raise_shape(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, bool]:
    """Whether the body raises anything, and whether any raise is bare.

    A bare `raise` re-raises whatever was caught, and nothing in the source
    names the type. The only honest response is to stop asking, which is why
    the caller skips the check entirely when it sees one.
    """
    raises = False
    bare = False
    for node in ast.walk(function):
        if isinstance(node, ast.Raise):
            raises = True
            if node.exc is None:
                bare = True
    return raises, bare


def _is_stub(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the body does nothing at all.

    An `@abstractmethod`, a protocol member, a `...` placeholder. Its docstring
    documents a **contract** its implementers must honour, and the declaration
    is the only place to state one — so `Raises:` and `Returns:` there are
    correct however little the body does.

    Reporting them was self-review S-04, and one false positive in the three
    findings this rule produced against its own repository. A body that does
    nothing cannot contradict anything.
    """
    body = [
        node
        for node in function.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    if not body:
        return True
    return len(body) == 1 and isinstance(body[0], ast.Pass)


def _returns_a_value(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and node.value is not None:
            return True
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
    return False


def docstring_defects(source: str) -> list[DocDefect]:
    """Where a function's docstring and its code disagree.

    Deliberately narrow in one direction. A documented exception is reported
    only when the function raises **nothing at all** — a function that raises
    `ValueError` and documents the `OSError` its callee raises is documenting
    the truth, and this module cannot see the callee. Reporting it would be the
    kind of confident wrongness the level exists to remove from documents.

    A file that will not parse yields nothing: a half-written branch is a
    reason to say less, the same answer the analysis suite has given since
    finding G-09.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    defects: list[DocDefect] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        docstring = ast.get_docstring(node)
        if not docstring:
            continue
        defect = _docstring_defect(node, docstring)
        if defect is not None:
            defects.append(defect)
    return defects


def _docstring_defect(function: ast.FunctionDef | ast.AsyncFunctionDef, docstring: str) -> DocDefect | None:
    documented = _documented(docstring)
    declared = _parameter_names(function)
    complaints: list[str] = []

    if documented.parameters:
        # Only when the docstring documents *some* parameters. A one-line
        # docstring is a style choice, and charging for it would make the rule
        # a nuisance rather than a check.
        invented = [name for name in documented.parameters if name not in declared]
        missing = [name for name in declared if name not in documented.parameters]
        if invented:
            complaints.append(f"documents ({', '.join(invented)}), not in the signature")
        if missing:
            complaints.append(f"signature has ({', '.join(missing)}), undocumented")

    # A stub is examined for what it says about its own signature and for
    # nothing else: there is no body to contradict (S-04).
    if not _is_stub(function):
        raises, bare = _raise_shape(function)
        if documented.raises and not raises and not bare:
            complaints.append(f"documents raising ({', '.join(documented.raises)}), the body raises nothing")

        if documented.returns and not _returns_a_value(function):
            complaints.append("documents a return value, every path returns None")

    if not complaints:
        return None
    return DocDefect(DOCSTRING_DRIFT, function.name, function.lineno, "", "; ".join(complaints))


@dataclass(frozen=True)
class Rename:
    """One name that became another in a single change."""

    old: str
    new: str

    def __post_init__(self) -> None:
        if not self.old or not self.new:
            raise ValueError("A rename names both the old and the new symbol.")
        if self.old == self.new:
            raise ValueError("A rename to the same name is not a rename.")


#: What kind of thing a line declares. A rename is two declarations of the
#: **same** kind: a function that became a function, a flag that became a flag.
#:
#: Counting names without their kinds called a deletion plus an unrelated
#: addition a rename — `start_app` "became" `MAX_RETRIES` — and offered a
#: one-click button substituting the wrong word into somebody's README
#: (self-review 27, S-02).
_KINDS: Mapping[str, str] = {
    "def": "function",
    "async def": "function",
    "class": "class",
}


def _declarations_on(line: str) -> set[tuple[str, str]]:
    """Every ``(kind, name)`` a single line of source declares."""
    found: set[tuple[str, str]] = set()

    definition = _DEFINES.match(line)
    if definition is not None:
        name = definition.group("name")
        if name:
            keyword = line.strip().split()[0]
            found.add((_KINDS.get(keyword, "function"), name))
        elif definition.group("constant"):
            found.add(("constant", definition.group("constant")))

    for match in _QUOTED.finditer(line):
        value = match.group("value")
        found.add(("option" if value.startswith("--") else "environment", value))

    return found


def rename_in(diff: str) -> Rename | None:
    """The rename a diff performed, or ``None``.

    Exactly one declaration removed and exactly one added, **of the same kind**.
    Two of each is ambiguous — which old name became which new one is not in the
    diff — and two of different kinds is not a rename at all: a function deleted
    beside a constant added is two changes, and substituting one for the other in
    a document is a wrong edit offered as a button (self-review 27, S-02).

    This is the whole of what makes a documentation edit offerable. The diff
    already knows both names, so the substitution is arithmetic rather than a
    sentence somebody has to review. Level 23 refused to suggest prose and that
    refusal stands; this is not prose.
    """
    removed: set[tuple[str, str]] = set()
    added: set[tuple[str, str]] = set()

    for line in diff.splitlines():
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("-"):
            removed |= _declarations_on(line[1:])
        elif line.startswith("+"):
            added |= _declarations_on(line[1:])

    gone = removed - added
    fresh = added - removed
    if len(gone) != 1 or len(fresh) != 1:
        return None

    (old_kind, old), (new_kind, new) = next(iter(gone)), next(iter(fresh))
    if old_kind != new_kind:
        return None

    try:
        return Rename(old=old, new=new)
    except ValueError:
        return None


def documentation_suggestion(path: str, text: str, line: int, rename: Rename) -> "Suggestion | None":
    """A suggestion substituting a renamed symbol on one line of a document.

    ``None`` when the line does not hold the old name as a whole word, when it
    is past the end, or when the substitution would change nothing. A partial
    word is refused: `start_application` is not `start_app`, and a substring
    rename is how a document acquires `create_applicationlication`.

    Every occurrence on the line is substituted rather than the first. Fixing
    the first of two is half a fix a reader reads as a whole one — the finding
    self-review 26 paid for in `fix_recipes.py`.
    """
    lines = text.splitlines()
    if not 1 <= line <= len(lines):
        return None

    pattern = re.compile(rf"\b{re.escape(rename.old)}\b")
    original = lines[line - 1]
    if not pattern.search(original):
        return None

    replaced = pattern.sub(rename.new, original)
    if replaced == original:
        return None

    try:
        return Suggestion.single(
            rule_id=f"{NAMESPACE_DOCS}.{DEAD_REFERENCE}",
            file_path=path,
            start_line=line,
            end_line=line,
            replacement=(replaced,),
            recipe="rename-in-documentation",
        )
    except ValueError:
        return None
