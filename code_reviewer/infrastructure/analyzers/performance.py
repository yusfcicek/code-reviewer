"""Complexity and resource use.

The performance problems that survive review are rarely subtle: a loop inside a
loop over the same collection, a query inside a loop, a file opened and never
closed. This analyzer looks for those shapes in the AST, where they are visible,
rather than in the text, where they are not.
"""

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from code_reviewer.domain.policy import PerformancePolicy
from code_reviewer.domain.severity import Severity
from code_reviewer.infrastructure.observability.logging import get_logger

logger = get_logger(__name__)


class PerformanceIssueType(Enum):
    """The kinds of performance problem this analyzer recognises."""

    HIGH_COMPLEXITY = "high_complexity"
    MEMORY_LEAK = "memory_leak"
    N_PLUS_ONE = "n_plus_one"
    INEFFICIENT_LOOP = "inefficient_loop"
    RESOURCE_LEAK = "resource_leak"
    UNNECESSARY_COPY = "unnecessary_copy"
    BLOCKING_OPERATION = "blocking_operation"
    LARGE_MEMORY = "large_memory"
    RECURSIVE_RISK = "recursive_risk"


@dataclass
class PerformanceIssue:
    """One performance problem, at one line."""

    issue_type: PerformanceIssueType
    severity: Severity
    line_number: int
    symbol_name: str
    description: str
    suggestion: str
    complexity: str = ""  # O(n), O(n²), etc.
    metrics: dict = field(default_factory=dict)


@dataclass
class ComplexityReport:
    """One function's estimated complexity."""

    function_name: str
    estimated_complexity: str
    nested_loops: int
    recursive: bool
    issues: list[PerformanceIssue] = field(default_factory=list)


@dataclass
class MemoryLeakRisk:
    """A resource that may never be released."""

    line_number: int
    resource_type: str  # "file", "connection", "socket", etc.
    description: str
    suggestion: str


@dataclass
class NPlusOnePattern:
    """A query issued once per loop iteration."""

    loop_line: int
    query_line: int
    description: str
    suggestion: str


@dataclass
class PerformanceReport:
    """Everything the performance scan found in one file."""

    file_path: str
    issues: list[PerformanceIssue] = field(default_factory=list)
    complexity_reports: list[ComplexityReport] = field(default_factory=list)
    memory_leak_risks: list[MemoryLeakRisk] = field(default_factory=list)
    n_plus_one_patterns: list[NPlusOnePattern] = field(default_factory=list)
    performance_score: int = 100
    summary: str = ""


class PerformanceAnalyzer:
    """
    Estimates complexity and finds resource problems.

    - nested loops, reported as O(n²) and worse
    - recursion, which may want memoisation
    - iteration that materialises more than it needs
    - resources opened without a context manager or a close
    - queries inside loops
    """

    # Calls that acquire something which must be released
    RESOURCE_OPENERS: ClassVar[dict[str, str]] = {
        "open": "file",
        "connect": "connection",
        "socket": "socket",
        "urlopen": "url_connection",
        "cursor": "database_cursor",
        "Session": "session",
        "Lock": "lock",
        "acquire": "lock",
        "pool.connection": "pool_connection",
    }

    # ...and the calls that release it
    RESOURCE_CLOSERS: ClassVar[set[str]] = {"close", "release", "disconnect", "shutdown"}

    # Calls that cross a process boundary
    #: Calls that mean a round trip, matched by *receiver* as well as by name.
    #:
    #: The receiver is what makes this usable. `.get(`, `.find(` and `.all(`
    #: were once matched on the method alone, and in Python those are far more
    #: often `dict.get`, `str.find` and the `all()` builtin than they are
    #: queries: dogfooding found seventeen hits across this package and not one
    #: touched a database (finding G-16). A rule that flags every `dict.get()`
    #: in a loop is a rule teams switch off, and switching it off costs them
    #: the real N+1 detections too.
    #:
    #: Unambiguous method names still match on any receiver; ambiguous ones
    #: require a receiver that names a client, a session or a cursor.
    DB_QUERY_PATTERNS: ClassVar[list[str]] = [
        # Unambiguous: these are not builtins or common container methods.
        r"\.execute\s*\(",
        r"\.executemany\s*\(",
        r"\.fetchone\s*\(",
        r"\.fetchall\s*\(",
        r"\.fetch\s*\(",
        r"\brequests\.\w+\s*\(",
        r"\bhttpx\.\w+\s*\(",
        r"\burlopen\s*\(",
        # Ambiguous method names, qualified by a receiver that means I/O.
        r"\b\w*(?:conn|connection|cursor|session|client|db|database|repo|repository|"
        r"query|queryset|objects|api|http|store)\w*"
        r"\.(?:get|find|filter|all|select|query|first|one|count|exists|delete|save)\s*\(",
    ]

    # Patterns that materialise more than they need to
    LARGE_MEMORY_PATTERNS: ClassVar[list[tuple[str, str]]] = [
        (r"\.readlines\s*\(\)", "reads entire file into memory"),
        (r"list\s*\([^)]*range\s*\([^)]*\)", "creates full list from range"),
        (r"\*\s*\d{4,}", "large allocation"),
    ]

    #: Loop nesting at or above which a function is reported. A
    #: PerformancePolicy overrides it, along with the switches for each rule
    #: family; configuring them used to have no effect (finding F-31).
    MAX_NESTED_LOOPS = 2

    def __init__(self, policy: PerformancePolicy | None = None):
        self._loop_depth = 0
        self._current_function = ""

        # A policy states the deepest acceptable nesting; the analyzer reports
        # anything deeper, so the alert threshold is one past the limit.
        self.max_nested_loops = policy.max_nested_loops if policy else self.MAX_NESTED_LOOPS
        self.alert_on_n_squared = policy.alert_on_n_squared if policy else True
        self.alert_on_n_plus_one = policy.alert_on_n_plus_one if policy else True
        self.alert_on_memory_leak = policy.alert_on_memory_leak if policy else True

    def analyze(self, content: str, file_path: str = "") -> PerformanceReport:
        """
        Analyses one file.

        Args:
            content: The file's text.
            file_path: Used to decide whether an AST pass is possible.

        Returns:
            PerformanceReport: the issues found, with a score and a summary.
        """
        report = PerformanceReport(file_path=file_path)

        # An AST makes loop nesting and resource lifetimes visible
        if file_path.endswith(".py"):
            try:
                tree = ast.parse(content)

                # Loop nesting and recursion
                report.complexity_reports = self._analyze_complexity(tree)

                # Resources opened and not released
                if self.alert_on_memory_leak:
                    report.memory_leak_risks = self._detect_memory_leaks(tree)

                # Queries inside loops
                if self.alert_on_n_plus_one:
                    report.n_plus_one_patterns = self._detect_n_plus_one(tree, content)

                # Quadratic string building
                report.issues.extend(self._detect_string_concat_in_loop(tree))

            except SyntaxError as exc:
                # Unparseable source means the AST pass contributes nothing;
                # the text pass below still runs. The reason is recorded
                # rather than discarded.
                logger.debug("Unparseable source; AST checks skipped", extra={"fields": {"error": str(exc)}})

        # Text patterns, for anything the AST pass could not cover
        report.issues.extend(self._analyze_patterns(content))

        # Fold every sub-report into one issue list
        report.issues.extend(self._collect_issues(report))

        # Reduce it to a score
        report.performance_score = self._calculate_score(report)

        # ...and a summary
        report.summary = self._generate_summary(report)

        return report

    def _analyze_complexity(self, tree: ast.AST) -> list[ComplexityReport]:
        """Estimates the complexity of every function in the module."""
        reports = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                report = self._analyze_function_complexity(node)
                if report.nested_loops > 0 or report.recursive:
                    reports.append(report)

        return reports

    def _analyze_function_complexity(
        self, func_node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> ComplexityReport:
        """Estimates one function's complexity from its loops and recursion."""
        max_depth = 0
        is_recursive = False

        # How deeply do loops nest?
        max_depth = self._find_max_loop_depth(func_node)

        # Does it call itself?
        is_recursive = self._is_recursive(func_node)

        # A rough class, useful for a reviewer rather than a proof
        if is_recursive:
            complexity = "O(2^n) or O(n!) - recursive, needs analysis"
        elif max_depth >= 3:
            complexity = f"O(n³) or worse - {max_depth} nested loops"
        elif max_depth == 2:
            complexity = "O(n²)"
        elif max_depth == 1:
            complexity = "O(n)"
        else:
            complexity = "O(1) or O(log n)"

        report = ComplexityReport(
            function_name=func_node.name,
            estimated_complexity=complexity,
            nested_loops=max_depth,
            recursive=is_recursive,
        )

        # Report what the estimate implies
        if self.alert_on_n_squared and max_depth >= self.max_nested_loops:
            report.issues.append(
                PerformanceIssue(
                    issue_type=PerformanceIssueType.HIGH_COMPLEXITY,
                    severity=Severity.HIGH if max_depth > self.max_nested_loops else Severity.MEDIUM,
                    line_number=func_node.lineno,
                    symbol_name=func_node.name,
                    description=f"Function has {max_depth} levels of nested loops",
                    suggestion="Consider using hash maps, caching, or algorithmic optimization",
                    complexity=complexity,
                    metrics={"loop_depth": max_depth},
                )
            )

        if is_recursive:
            report.issues.append(
                PerformanceIssue(
                    issue_type=PerformanceIssueType.RECURSIVE_RISK,
                    severity=Severity.MEDIUM,
                    line_number=func_node.lineno,
                    symbol_name=func_node.name,
                    description="Recursive function - check for memoization opportunities",
                    suggestion="Consider adding @lru_cache decorator or manual memoization",
                    complexity=complexity,
                    metrics={"recursive": True},
                )
            )

        return report

    def _find_max_loop_depth(self, node: ast.AST, current_depth: int = 0) -> int:
        """The deepest loop nesting anywhere under this node."""
        max_depth = current_depth

        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                child_depth = self._find_max_loop_depth(child, current_depth + 1)
                max_depth = max(max_depth, child_depth)
            elif isinstance(child, ast.comprehension):
                # A comprehension is a loop too
                child_depth = self._find_max_loop_depth(child, current_depth + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = self._find_max_loop_depth(child, current_depth)
                max_depth = max(max_depth, child_depth)

        return max_depth

    def _is_recursive(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """True when the function calls itself."""
        func_name = func_node.name

        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == func_name:
                    return True
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr == func_name:
                        return True

        return False

    def _detect_memory_leaks(self, tree: ast.AST) -> list[MemoryLeakRisk]:
        """Finds resources that may never be released."""
        risks: list[MemoryLeakRisk] = []

        for node in ast.walk(tree):
            # open() without context manager
            # One assignment produces one risk. Iterating the targets meant
            # `handle = backup = open(path)` reported the same leak twice.
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                self._check_resource_assignment(node, risks)

            # Direct call without assignment (potential leak)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                func_name = self._get_call_name(call)
                if func_name in self.RESOURCE_OPENERS:
                    risks.append(
                        MemoryLeakRisk(
                            line_number=node.lineno,
                            resource_type=self.RESOURCE_OPENERS[func_name],
                            description=f"'{func_name}()' called but result not stored - potential leak",
                            suggestion="Store the resource handle and ensure proper cleanup",
                        )
                    )

        # Check for missing close() calls on stored resources
        risks.extend(self._check_unclosed_resources(tree))

        return risks

    def _check_resource_assignment(self, node: ast.Assign, risks: list[MemoryLeakRisk]):
        """Flags a resource acquired outside a context manager."""
        call = node.value
        if not isinstance(call, ast.Call):
            return

        func_name = self._get_call_name(call)

        if func_name in self.RESOURCE_OPENERS:
            # Inside a `with`, cleanup is guaranteed
            parent = getattr(node, "_parent", None)
            if not isinstance(parent, ast.With):
                risks.append(
                    MemoryLeakRisk(
                        line_number=node.lineno,
                        resource_type=self.RESOURCE_OPENERS[func_name],
                        description=f"'{func_name}()' used without 'with' statement",
                        suggestion="Use context manager: with open(...) as f:",
                    )
                )

    def _check_unclosed_resources(self, tree: ast.AST) -> list[MemoryLeakRisk]:
        """Finds resources assigned to a name and never closed."""
        risks = []
        opened_resources: dict[str, int] = {}  # var_name -> line_number

        for node in ast.walk(tree):
            # Acquired here...
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func_name = self._get_call_name(node.value)
                if func_name in self.RESOURCE_OPENERS:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            opened_resources[target.id] = node.lineno

            # ...released here
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in self.RESOURCE_CLOSERS:
                    if isinstance(node.func.value, ast.Name):
                        var_name = node.func.value.id
                        opened_resources.pop(var_name, None)

        # Whatever is left was never released
        for var_name, line_no in opened_resources.items():
            risks.append(
                MemoryLeakRisk(
                    line_number=line_no,
                    resource_type="unknown",
                    description=f"Resource '{var_name}' may not be properly closed",
                    suggestion="Ensure .close() is called or use context manager",
                )
            )

        return risks

    def _get_call_name(self, call: ast.Call) -> str:
        """The name of the function being called, however it is referenced."""
        if isinstance(call.func, ast.Name):
            return call.func.id
        elif isinstance(call.func, ast.Attribute):
            return call.func.attr
        return ""

    def _detect_n_plus_one(self, tree: ast.AST, content: str) -> list[NPlusOnePattern]:
        """Finds queries issued once per loop iteration."""
        patterns = []
        lines = content.split("\n")

        # Matching is done against the *line*, and a chained expression such
        # as `session.query(Model).first()` is several Call nodes on one line.
        # Without this, one round trip would be reported once per node.
        reported: set[tuple[int, int]] = set()

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                loop_line = node.lineno

                # Does anything inside this loop cross a process boundary?
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and hasattr(child, "lineno"):
                        if (loop_line, child.lineno) in reported:
                            continue
                        call_line_content = lines[child.lineno - 1] if child.lineno <= len(lines) else ""

                        for pattern in self.DB_QUERY_PATTERNS:
                            if re.search(pattern, call_line_content):
                                reported.add((loop_line, child.lineno))
                                patterns.append(
                                    NPlusOnePattern(
                                        loop_line=loop_line,
                                        query_line=child.lineno,
                                        description=(f"Database/API call inside loop at line {child.lineno}"),
                                        suggestion=(
                                            "Batch the queries: fetch all data before the "
                                            "loop or use eager loading"
                                        ),
                                    )
                                )
                                break

        return patterns

    def _detect_string_concat_in_loop(self, tree: ast.AST) -> list[PerformanceIssue]:
        """Reports ``s += "..."`` inside a loop, which rebuilds the string each pass.

        This used to be attempted with a text heuristic that asked
        ``'for ' in lines[a:b]`` — a membership test against a *list*, which is
        only true if some line equals ``"for "`` exactly. It could never fire
        (finding F-05).

        Working from the AST also removes the false positives the text version
        would have produced: only augmented additions whose right-hand side
        contains a string literal are reported, so numeric accumulators such as
        ``total += item`` stay quiet.
        """
        issues = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                continue

            for child in ast.walk(node):
                if not isinstance(child, ast.AugAssign) or not isinstance(child.op, ast.Add):
                    continue
                if not self._contains_string_literal(child.value):
                    continue

                target = child.target
                name = target.id if isinstance(target, ast.Name) else ""
                issues.append(
                    PerformanceIssue(
                        issue_type=PerformanceIssueType.INEFFICIENT_LOOP,
                        severity=Severity.LOW,
                        line_number=child.lineno,
                        symbol_name=name,
                        description=(
                            f"String concatenation with += inside a loop (line {child.lineno}) is O(n²)"
                        ),
                        suggestion=("Collect the parts in a list and ''.join(...) once, or use io.StringIO"),
                    )
                )

        return issues

    def _contains_string_literal(self, node: ast.AST) -> bool:
        """True when the expression mentions a string constant or an f-string."""
        for child in ast.walk(node):
            if isinstance(child, ast.JoinedStr):
                return True
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                return True
        return False

    def _analyze_patterns(self, content: str) -> list[PerformanceIssue]:
        """Text-level patterns, for what the AST pass cannot see."""
        issues = []
        lines = content.split("\n")

        for line_no, line in enumerate(lines, 1):
            # Large memory patterns
            for pattern, desc in self.LARGE_MEMORY_PATTERNS:
                if re.search(pattern, line):
                    issues.append(
                        PerformanceIssue(
                            issue_type=PerformanceIssueType.LARGE_MEMORY,
                            severity=Severity.MEDIUM,
                            line_number=line_no,
                            symbol_name="",
                            description=desc,
                            suggestion="Consider using generators or chunked processing",
                        )
                    )

            # Blocking I/O patterns
            blocking_patterns = [
                (r"time\.sleep\s*\(", "Blocking sleep call"),
                (r"requests\.\w+\s*\([^)]+\)\s*$", "Synchronous HTTP request"),
            ]
            for pattern, desc in blocking_patterns:
                if re.search(pattern, line):
                    issues.append(
                        PerformanceIssue(
                            issue_type=PerformanceIssueType.BLOCKING_OPERATION,
                            severity=Severity.LOW,
                            line_number=line_no,
                            symbol_name="",
                            description=desc,
                            suggestion="Consider async/await for better concurrency",
                        )
                    )

        return issues

    def _collect_issues(self, report: PerformanceReport) -> list[PerformanceIssue]:
        """Folds every sub-report into one issue list."""
        issues = []

        # Complexity issues
        for comp_report in report.complexity_reports:
            issues.extend(comp_report.issues)

        # Memory leak risks
        for risk in report.memory_leak_risks:
            issues.append(
                PerformanceIssue(
                    issue_type=PerformanceIssueType.MEMORY_LEAK,
                    severity=Severity.HIGH,
                    line_number=risk.line_number,
                    symbol_name=risk.resource_type,
                    description=risk.description,
                    suggestion=risk.suggestion,
                )
            )

        # N+1 patterns
        for pattern in report.n_plus_one_patterns:
            issues.append(
                PerformanceIssue(
                    issue_type=PerformanceIssueType.N_PLUS_ONE,
                    severity=Severity.HIGH,
                    line_number=pattern.loop_line,
                    symbol_name="",
                    description=pattern.description,
                    suggestion=pattern.suggestion,
                )
            )

        return issues

    def _calculate_score(self, report: PerformanceReport) -> int:
        """Reduces the issues to a score out of 100."""
        score = 100

        severity_penalties = {
            Severity.CRITICAL: 20,
            Severity.HIGH: 10,
            Severity.MEDIUM: 5,
            Severity.LOW: 2,
        }

        for issue in report.issues:
            score -= severity_penalties.get(issue.severity, 5)

        return max(0, score)

    def _generate_summary(self, report: PerformanceReport) -> str:
        """A short summary a reviewer reads before the issue list."""
        parts = []

        score = report.performance_score
        if score >= 90:
            emoji = "🟢"
            grade = "Excellent"
        elif score >= 70:
            emoji = "🟡"
            grade = "Good"
        elif score >= 50:
            emoji = "🟠"
            grade = "Needs Optimization"
        else:
            emoji = "🔴"
            grade = "Poor"

        parts.append(f"{emoji} **Performance Score**: {score}/100 ({grade})")

        # Functions worth looking at first
        high_complexity = [r for r in report.complexity_reports if r.nested_loops >= 2]
        if high_complexity:
            parts.append(f"\n⚠️ **High Complexity Functions**: {len(high_complexity)}")
            for r in high_complexity[:3]:
                parts.append(f"  - `{r.function_name}`: {r.estimated_complexity}")

        # N+1 patterns
        if report.n_plus_one_patterns:
            parts.append(f"\n🔄 **N+1 Query Patterns**: {len(report.n_plus_one_patterns)}")

        # Memory leak risks
        if report.memory_leak_risks:
            parts.append(f"\n💾 **Memory Leak Risks**: {len(report.memory_leak_risks)}")

        # Issue breakdown
        issue_types: dict[str, int] = {}
        for issue in report.issues:
            issue_types[issue.issue_type.value] = issue_types.get(issue.issue_type.value, 0) + 1

        if issue_types:
            parts.append("\n**Issue Breakdown**:")
            for itype, count in sorted(issue_types.items(), key=lambda x: -x[1]):
                parts.append(f"  - {itype}: {count}")

        return "\n".join(parts)


def analyze_performance(content: str, file_path: str = "", policy: PerformancePolicy | None = None) -> str:
    """
    Runs the analysis and renders it as markdown, for the agent's tool call.

    Args:
        content: The file's text.
        file_path: Used to decide whether an AST pass is possible.

    Returns:
        The report as markdown.
    """
    analyzer = PerformanceAnalyzer(policy)
    report = analyzer.analyze(content, file_path)

    output = [f"## ⚡ Performance Analysis: `{file_path or 'Code'}`\n"]
    output.append(report.summary)

    if report.issues:
        output.append("\n### Performance Issues:\n")

        # Most severe first: the truncation below must not drop them
        sorted_issues = sorted(report.issues, key=lambda issue: issue.severity)

        for issue in sorted_issues[:15]:  # Max 15 issue
            severity_icon = {
                Severity.CRITICAL: "🔴",
                Severity.HIGH: "🟠",
                Severity.MEDIUM: "🟡",
                Severity.LOW: "🟢",
            }

            output.append(
                f"#### {severity_icon.get(issue.severity, '')} "
                f"Line {issue.line_number}: {issue.issue_type.value}"
            )
            if issue.complexity:
                output.append(f"**Complexity**: {issue.complexity}")
            output.append(f"**Issue**: {issue.description}")
            output.append(f"**Fix**: {issue.suggestion}\n")

    return "\n".join(output)
