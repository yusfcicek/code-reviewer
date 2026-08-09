"""SQL built into a local, then executed.

The regex rule for `SAST.SQL_INJECTION` matches `execute\\s*\\([^)]*\\+` — a
concatenation *inside* the call. Nobody writes it that way. The ordinary
spelling builds the query into a variable on one line and executes the variable
on the next, and a line-oriented pattern cannot see across that gap.

The evaluation harness built at Level 12 charged the miss the moment it existed:
it is the whole of the committed recall gap, recorded as E-01. Closing it needs
an assignment followed, which is a question about a syntax tree rather than
about a line — so this lives in its own module, and the regex tables stay what
they are good at.

The pass is deliberately shallow. It follows local assignments inside one
scope, treats reassignment as clearing, and reports where the string was
*built* rather than where it was executed, because that is the line someone has
to change. It does not follow values across functions, into containers, or
through calls. A deeper analysis would find more, and would also start
inventing findings — which the same harness now charges for, in the other
direction.
"""

import ast
from dataclasses import dataclass

#: Statement keywords that make a string a query rather than a sentence.
#: Checked case-insensitively against the *literal* parts of a built string.
_SQL_KEYWORDS = ("select ", "insert ", "update ", "delete ", "drop ", "alter ", "truncate ")

#: Cursor and connection methods that send a string to a database.
_EXECUTORS = frozenset({"execute", "executemany", "executescript", "executescalar"})

#: How the string was built, in the order the checks run.
CONCATENATION = "concatenation"
PERCENT_FORMATTING = "%-formatting"
STR_FORMAT = "str.format"
F_STRING = "f-string"


@dataclass(frozen=True)
class TaintedQuery:
    """A query built from something that is not a literal, and then executed."""

    line_number: int
    """Where the string was built. The line someone has to change."""

    variable: str
    how: str
    evidence: str
    executed_at: int
    """Where it reached the database. Named in the description, so the reader
    can see both halves of a defect that spans two lines."""


def find_sql_taint(source: str) -> list[TaintedQuery]:
    """Every dynamically built query in ``source`` that reaches an executor.

    Returns an empty list for anything that does not parse. A half-written
    branch is a reason to say less, not a reason to abort the file's analysis
    (the rule `StaticAnalysisSuite` already applies to every analyzer).
    """
    if not source.strip():
        return []

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []

    found: list[TaintedQuery] = []
    for scope in _scopes(tree):
        found.extend(_scan(scope))

    # Sorted by where the defect is, and one report per built string however
    # often it is executed.
    return sorted(found, key=lambda query: query.line_number)


# -- internals --------------------------------------------------------------


def _scopes(tree: ast.AST) -> list[list[ast.stmt]]:
    """Every statement body that has its own local names.

    A name reused in another function is a different variable. Treating the
    module as one namespace is how a taint pass earns its reputation for noise.
    """
    bodies: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            bodies.append(list(node.body))
    return bodies


def _scan(body: list[ast.stmt]) -> list[TaintedQuery]:
    """Walks one scope in order, tracking which locals hold a built query."""
    tainted: dict[str, TaintedQuery] = {}
    reported: set[str] = set()
    found: list[TaintedQuery] = []

    for statement in _in_order(body):
        # Execution is checked first: a name used on the same line it is
        # assigned was assigned by an earlier statement or not at all.
        for name, execution_line in _executed_names(statement):
            candidate = tainted.get(name)
            if candidate is not None and name not in reported:
                reported.add(name)
                found.append(
                    TaintedQuery(
                        line_number=candidate.line_number,
                        variable=candidate.variable,
                        how=candidate.how,
                        evidence=candidate.evidence,
                        executed_at=execution_line,
                    )
                )

        _apply_assignment(statement, tainted, reported)

    return found


def _in_order(body: list[ast.stmt]) -> list[ast.stmt]:
    """Statements of one scope, including nested blocks, in source order.

    Nested *scopes* are excluded: those are visited on their own, with their
    own name bindings.
    """
    statements: list[ast.stmt] = []

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            statements.append(node)
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(node, field, []) or [])
            for handler in getattr(node, "handlers", []) or []:
                visit(handler.body)

    visit(body)
    return sorted(statements, key=lambda node: (node.lineno, node.col_offset))


def _apply_assignment(statement: ast.stmt, tainted: dict[str, TaintedQuery], reported: set[str]) -> None:
    """Records, propagates or clears taint for a simple assignment."""
    if not isinstance(statement, ast.Assign | ast.AnnAssign):
        return

    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    names = [target.id for target in targets if isinstance(target, ast.Name)]
    if not names or statement.value is None:
        return

    built = _built_query(statement.value)
    origin_line = statement.lineno

    if built is None and isinstance(statement.value, ast.Name):
        # One hop: `query = built`. Transitive by construction, because the
        # source name is only in the map if it was itself tainted. The origin
        # line travels with it — the defect is where the string was built, and
        # rebinding it to another name does not move that.
        source = tainted.get(statement.value.id)
        if source is not None:
            built = _BuiltQuery(source.how, source.evidence)
            origin_line = source.line_number

    for name in names:
        if built is None:
            # Reassignment to something safe clears the taint, and lets the
            # name be reported again if it is later rebuilt unsafely.
            tainted.pop(name, None)
            reported.discard(name)
        else:
            tainted[name] = TaintedQuery(
                line_number=origin_line,
                variable=name,
                how=built.how,
                evidence=built.evidence,
                executed_at=0,
            )


def _executed_names(statement: ast.stmt) -> list[tuple[str, int]]:
    """Names passed as the first argument to an executor, within ``statement``."""
    executed: list[tuple[str, int]] = []

    for node in ast.walk(statement):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if _callee_name(node.func) not in _EXECUTORS:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name):
            executed.append((first.id, node.lineno))

    return executed


def _callee_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


@dataclass(frozen=True)
class _BuiltQuery:
    how: str
    evidence: str


def _built_query(value: ast.expr) -> _BuiltQuery | None:
    """Whether ``value`` builds a SQL string out of something non-literal.

    Four spellings, one per checker below. Each needs both halves: a literal
    part that looks like a query, and a part that is not a literal.
    `"SELECT * FROM " + "users"` is dynamic in neither sense, and
    `"hello " + name` is dynamic and not a query.
    """
    for checker in (_from_concatenation, _from_percent, _from_fstring, _from_format):
        built = checker(value)
        if built is not None:
            return built
    return None


def _from_concatenation(value: ast.expr) -> _BuiltQuery | None:
    """`"SELECT ... " + name`, however deeply the additions nest."""
    if not (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)):
        return None

    parts = _flatten_addition(value)
    literals = [part for part in parts if _is_string_constant(part)]
    if not literals or len(literals) == len(parts):
        return None

    text = _join(literals)
    return _BuiltQuery(CONCATENATION, text) if _looks_like_sql(text) else None


def _from_percent(value: ast.expr) -> _BuiltQuery | None:
    """`"SELECT ... %s" % name`."""
    if not (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mod)):
        return None

    text = _constant_text(value.left)
    return _BuiltQuery(PERCENT_FORMATTING, text) if _looks_like_sql(text) else None


def _from_fstring(value: ast.expr) -> _BuiltQuery | None:
    """`f"SELECT ... {name}"`, but not an f-string with nothing interpolated."""
    if not isinstance(value, ast.JoinedStr):
        return None
    if not any(isinstance(part, ast.FormattedValue) for part in value.values):
        return None

    text = _join([part for part in value.values if isinstance(part, ast.Constant)])
    return _BuiltQuery(F_STRING, text) if _looks_like_sql(text) else None


def _from_format(value: ast.expr) -> _BuiltQuery | None:
    """`"SELECT ... {}".format(name)`."""
    if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)):
        return None
    if value.func.attr != "format":
        return None

    text = _constant_text(value.func.value)
    return _BuiltQuery(STR_FORMAT, text) if _looks_like_sql(text) else None


def _constant_text(node: ast.expr) -> str:
    """The text of a string constant, or empty for anything else.

    Written as an `isinstance` chain rather than through the predicate below,
    because that is what narrows the type: a helper returning `bool` tells the
    checker nothing about `node.value`.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _flatten_addition(node: ast.expr) -> list[ast.expr]:
    """`a + b + c` as three operands rather than a left-leaning tree."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flatten_addition(node.left) + _flatten_addition(node.right)
    return [node]


def _is_string_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _join(nodes: list[ast.expr]) -> str:
    """The literal parts of a built string, in order, space-separated."""
    return " ".join(text for text in map(_constant_text, nodes) if text)


def _looks_like_sql(text: str) -> bool:
    lowered = f"{text.lower()} "
    return any(keyword in lowered for keyword in _SQL_KEYWORDS)
