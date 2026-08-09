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
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar


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
        if name in self.signatures:
            return self.signatures[name]
        return self.signatures.get(name.rsplit(".", 1)[-1])

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


def _claim_from_span(token: str, line: int, heading: str) -> DocumentClaim | None:
    """One inline code span, classified — or nothing, which is the common case."""
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

    if _symbol_shaped(token):
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


def claims_in(text: str) -> list[DocumentClaim]:
    """Every claim a Markdown document makes, in document order.

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
                            source="".join(f"{held}\n" for held in fenced),
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
            claim = _claim_from_span(token, number, heading)
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
