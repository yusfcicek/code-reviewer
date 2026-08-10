"""Design quality: SOLID, duplication, testability and error handling.

These are the observations a reviewer makes when the code works but will be
unpleasant to live with: a class doing four things, a function nobody can call
without constructing half the world, an `except` that swallows the reason.

Thresholds come from the policy rather than from constants, so a team decides
what "too many" means for their codebase.
"""

import ast
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from code_reviewer.domain.policy import QualityPolicy
from code_reviewer.domain.severity import Severity
from code_reviewer.infrastructure.observability.logging import get_logger

logger = get_logger(__name__)


class IssueCategory(Enum):
    """The kinds of design problem this analyzer recognises."""

    SOLID_SRP = "solid_srp"  # Single Responsibility
    SOLID_OCP = "solid_ocp"  # Open/Closed
    SOLID_LSP = "solid_lsp"  # Liskov Substitution
    SOLID_ISP = "solid_isp"  # Interface Segregation
    SOLID_DIP = "solid_dip"  # Dependency Inversion
    DRY = "dry"  # Don't Repeat Yourself
    TESTABILITY = "testability"
    ERROR_HANDLING = "error_handling"
    CODE_SMELL = "code_smell"
    MAINTAINABILITY = "maintainability"


@dataclass
class QualityIssue:
    """One design problem, at one line."""

    category: IssueCategory
    severity: Severity
    line_number: int
    symbol_name: str
    description: str
    suggestion: str
    metrics: dict = field(default_factory=dict)


@dataclass
class DuplicateBlock:
    """A block of code that appears in more than one place."""

    hash: str
    locations: list[tuple[int, int]] = field(default_factory=list)  # (start_line, end_line)
    content_preview: str = ""
    line_count: int = 0


@dataclass
class SOLIDReport:
    """SOLID violations, grouped by principle."""

    srp_issues: list[QualityIssue] = field(default_factory=list)
    ocp_issues: list[QualityIssue] = field(default_factory=list)
    lsp_issues: list[QualityIssue] = field(default_factory=list)
    isp_issues: list[QualityIssue] = field(default_factory=list)
    dip_issues: list[QualityIssue] = field(default_factory=list)

    def total_issues(self) -> int:
        return (
            len(self.srp_issues)
            + len(self.ocp_issues)
            + len(self.lsp_issues)
            + len(self.isp_issues)
            + len(self.dip_issues)
        )


@dataclass
class TestabilityScore:
    """How hard the code will be to test, as a score out of 100."""

    score: int  # 0-100
    issues: list[QualityIssue] = field(default_factory=list)
    summary: str = ""


@dataclass
class ErrorHandlingReport:
    """How the code handles failure."""

    issues: list[QualityIssue] = field(default_factory=list)
    try_catch_count: int = 0
    empty_catches: int = 0
    generic_exceptions: int = 0
    missing_finally: int = 0


@dataclass
class QualityReport:
    """Everything the quality scan found in one file."""

    file_path: str
    solid_report: SOLIDReport = field(default_factory=SOLIDReport)
    duplicates: list[DuplicateBlock] = field(default_factory=list)
    testability: TestabilityScore | None = None
    error_handling: ErrorHandlingReport | None = None
    all_issues: list[QualityIssue] = field(default_factory=list)
    quality_score: int = 100
    summary: str = ""


class QualityAnalyzer:
    """
    Checks SOLID principles, duplication, testability and error handling.
    """

    # Defaults, used when no policy is supplied. A QualityPolicy overrides
    # each of them: configuring a threshold used to have no effect because the
    # analyzer always read these constants (finding F-31).
    MAX_CLASS_METHODS = 10  # SRP: public methods per class
    MAX_FUNCTION_LINES = 50  # SRP: lines per function
    MAX_FUNCTION_PARAMS = 5  # Testability: Max parametre
    MAX_CYCLOMATIC_COMPLEXITY = 10  # Max cyclomatic complexity
    MIN_DUPLICATE_LINES = 5  # shortest block worth calling duplication

    def __init__(self, policy: QualityPolicy | None = None):
        self._class_info: dict[str, dict] = {}
        self._function_info: dict[str, dict] = {}

        self.max_class_methods = policy.max_class_methods if policy else self.MAX_CLASS_METHODS
        self.max_function_lines = policy.max_function_lines if policy else self.MAX_FUNCTION_LINES
        self.max_cyclomatic_complexity = (
            policy.max_cyclomatic_complexity if policy else self.MAX_CYCLOMATIC_COMPLEXITY
        )
        self.min_duplicate_lines = policy.min_duplicate_lines if policy else self.MIN_DUPLICATE_LINES
        self.max_function_params = self.MAX_FUNCTION_PARAMS
        self.enforce_srp = policy.enforce_srp if policy else True
        self.enforce_dip = policy.enforce_dip if policy else True

    def analyze(self, content: str, file_path: str = "") -> QualityReport:
        """
        Analyses one file.
        """
        report = QualityReport(file_path=file_path)

        # SOLID and error handling need an AST
        if file_path.endswith(".py"):
            try:
                tree = ast.parse(content)
                report.solid_report = self.check_solid_principles(tree, content)
                report.testability = self.analyze_testability(tree, content)
                report.error_handling = self.check_error_handling(tree)
            except SyntaxError as exc:
                logger.debug("Unparseable source; AST checks skipped", extra={"fields": {"error": str(exc)}})

        # Duplication is text-level, so it works for any language
        report.duplicates = self.detect_duplicates(content)

        # Fold every sub-report into one issue list
        report.all_issues = self._collect_all_issues(report)

        # Reduce it to a score
        report.quality_score = self._calculate_quality_score(report)

        # ...and a summary
        report.summary = self._generate_summary(report)

        return report

    def check_solid_principles(self, tree: ast.AST, content: str) -> SOLIDReport:
        """Checks each SOLID principle the policy asks for."""
        report = SOLIDReport()

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Single Responsibility
                if self.enforce_srp:
                    report.srp_issues.extend(self._check_srp(node))

                # Dependency Inversion
                if self.enforce_dip:
                    report.dip_issues.extend(self._check_dip(node))

                # Interface Segregation, for abstract classes only
                if self._is_abstract_class(node):
                    isp_issues = self._check_isp(node)
                    report.isp_issues.extend(isp_issues)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # A function too long to hold in one head
                srp_issues = self._check_function_srp(node, content)
                report.srp_issues.extend(srp_issues)

        return report

    def _check_srp(self, class_node: ast.ClassDef) -> list[QualityIssue]:
        """Flags classes doing more than one job."""
        issues = []

        # Public surface: how much does this class promise?
        method_count = sum(
            1
            for item in class_node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_")
        )

        if method_count > self.max_class_methods:
            issues.append(
                QualityIssue(
                    category=IssueCategory.SOLID_SRP,
                    severity=Severity.MEDIUM,
                    line_number=class_node.lineno,
                    symbol_name=class_node.name,
                    description=(
                        f"Class '{class_node.name}' has {method_count} public methods (max: "
                        f"{self.max_class_methods})"
                    ),
                    suggestion=(
                        "Consider splitting into multiple smaller classes with focused responsibilities"
                    ),
                    metrics={"method_count": method_count},
                )
            )

        # State: how much does it hold?
        init_method = None
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                init_method = item
                break

        if init_method:
            instance_vars = self._count_instance_variables(init_method)
            if instance_vars > 7:
                issues.append(
                    QualityIssue(
                        category=IssueCategory.SOLID_SRP,
                        severity=Severity.MEDIUM,
                        line_number=class_node.lineno,
                        symbol_name=class_node.name,
                        description=f"Class '{class_node.name}' has {instance_vars} instance variables",
                        suggestion=(
                            "Many instance variables may indicate mixed responsibilities. "
                            "Consider composition."
                        ),
                        metrics={"instance_vars": instance_vars},
                    )
                )

        return issues

    def _check_function_srp(
        self, func_node: ast.FunctionDef | ast.AsyncFunctionDef, content: str
    ) -> list[QualityIssue]:
        """Flags functions that are too long or too branchy."""
        issues = []

        # Length. `end_lineno` is Optional on every AST node, and `hasattr`
        # does not narrow that — a node carrying `end_lineno=None` would have
        # raised a TypeError here rather than skipping the check.
        if func_node.end_lineno is not None:
            line_count = func_node.end_lineno - func_node.lineno + 1
            if line_count > self.max_function_lines:
                issues.append(
                    QualityIssue(
                        category=IssueCategory.SOLID_SRP,
                        severity=Severity.MEDIUM,
                        line_number=func_node.lineno,
                        symbol_name=func_node.name,
                        description=(
                            f"Function '{func_node.name}' is {line_count} lines (max: "
                            f"{self.max_function_lines})"
                        ),
                        suggestion="Break down into smaller, focused functions",
                        metrics={"line_count": line_count},
                    )
                )

        # ...and branching
        complexity = self._calculate_cyclomatic_complexity(func_node)
        if complexity > self.max_cyclomatic_complexity:
            issues.append(
                QualityIssue(
                    category=IssueCategory.MAINTAINABILITY,
                    severity=Severity.HIGH,
                    line_number=func_node.lineno,
                    symbol_name=func_node.name,
                    description=f"Function '{func_node.name}' has high cyclomatic complexity: {complexity}",
                    suggestion="Reduce branching by extracting helper functions or using polymorphism",
                    metrics={"cyclomatic_complexity": complexity},
                )
            )

        return issues

    def _check_dip(self, class_node: ast.ClassDef) -> list[QualityIssue]:
        """Flags a class that constructs its own dependencies."""
        issues = []

        # A concrete class built in __init__ cannot be substituted in a test
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                for stmt in ast.walk(item):
                    if isinstance(stmt, ast.Call):
                        if isinstance(stmt.func, ast.Name):
                            # Capitalised names are classes by convention
                            if stmt.func.id[0].isupper() and stmt.func.id not in [
                                "Type",
                                "Dict",
                                "List",
                                "Set",
                                "Optional",
                            ]:
                                issues.append(
                                    QualityIssue(
                                        category=IssueCategory.SOLID_DIP,
                                        severity=Severity.LOW,
                                        line_number=stmt.lineno
                                        if hasattr(stmt, "lineno")
                                        else class_node.lineno,
                                        symbol_name=class_node.name,
                                        description=(
                                            f"Class '{class_node.name}' instantiates concrete "
                                            f"class '{stmt.func.id}' in __init__"
                                        ),
                                        suggestion=(
                                            "Consider dependency injection - pass the dependency "
                                            "as a constructor parameter"
                                        ),
                                        metrics={"concrete_class": stmt.func.id},
                                    )
                                )

        return issues

    def _check_isp(self, class_node: ast.ClassDef) -> list[QualityIssue]:
        """Flags interfaces that demand too much of an implementer."""
        issues = []

        # How much does an implementer have to provide?
        abstract_methods = []
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
                        abstract_methods.append(item.name)

        if len(abstract_methods) > 7:
            issues.append(
                QualityIssue(
                    category=IssueCategory.SOLID_ISP,
                    severity=Severity.MEDIUM,
                    line_number=class_node.lineno,
                    symbol_name=class_node.name,
                    description=(
                        f"Interface '{class_node.name}' has {len(abstract_methods)} abstract methods"
                    ),
                    suggestion="Consider splitting into smaller, more focused interfaces",
                    metrics={"abstract_method_count": len(abstract_methods)},
                )
            )

        return issues

    def _is_abstract_class(self, class_node: ast.ClassDef) -> bool:
        """True when the class is meant to be subclassed rather than used."""
        # Explicit ABC inheritance...
        for base in class_node.bases:
            if isinstance(base, ast.Name) and base.id in ["ABC", "ABCMeta"]:
                return True
            if isinstance(base, ast.Attribute) and base.attr in ["ABC", "ABCMeta"]:
                return True

        # ...or an abstract method, which amounts to the same thing
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
                        return True

        return False

    def _count_instance_variables(self, init_method: ast.FunctionDef) -> int:
        """Counts the attributes a constructor assigns."""
        count = 0
        for stmt in ast.walk(init_method):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Attribute):
                        if isinstance(target.value, ast.Name) and target.value.id == "self":
                            count += 1
        return count

    def _calculate_cyclomatic_complexity(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """Counts the independent paths through a function."""
        complexity = 1  # Base complexity

        for node in ast.walk(func_node):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
            elif isinstance(node, ast.comprehension):
                complexity += 1
                if node.ifs:
                    complexity += len(node.ifs)

        return complexity

    def detect_duplicates(self, content: str) -> list[DuplicateBlock]:
        """Finds identical blocks repeated in the file."""
        duplicates = []
        lines = content.split("\n")

        # Normalise first: indentation and spacing are not duplication
        normalized_lines = []
        for i, line in enumerate(lines):
            normalized = self._normalize_line(line)
            if normalized:  # blank lines are not code
                normalized_lines.append((i + 1, normalized))

        # Hash a sliding window of lines
        block_size = self.min_duplicate_lines
        block_hashes: dict[str, list[int]] = defaultdict(list)

        for i in range(len(normalized_lines) - block_size + 1):
            block = [nl[1] for nl in normalized_lines[i : i + block_size]]
            # Not a security hash: this buckets identical blocks so the
            # duplicate-code check can compare them. `usedforsecurity=False`
            # says so to the reader and to the FIPS-restricted builds where
            # md5 is otherwise unavailable.
            block_hash = hashlib.md5("\n".join(block).encode(), usedforsecurity=False).hexdigest()
            start_line = normalized_lines[i][0]
            block_hashes[block_hash].append(start_line)

        # A hash seen twice is a block seen twice
        for hash_val, starts in block_hashes.items():
            if len(starts) > 1:
                duplicates.append(
                    DuplicateBlock(
                        hash=hash_val,
                        locations=[(s, s + block_size - 1) for s in starts],
                        content_preview=lines[starts[0] - 1] if starts else "",
                        line_count=block_size,
                    )
                )

        return duplicates

    def _normalize_line(self, line: str) -> str:
        """Normalises a line so that formatting does not hide duplication."""
        stripped = line.strip()

        # Comments and blanks are not code
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            return ""

        # Collapse runs of whitespace
        return re.sub(r"\s+", " ", stripped)

    def analyze_testability(self, tree: ast.AST, content: str) -> TestabilityScore:
        """Scores how easily the code can be tested."""
        issues = []
        score = 100

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Every parameter is another thing a test has to construct
                param_count = len(node.args.args)
                if param_count > self.max_function_params:
                    issues.append(
                        QualityIssue(
                            category=IssueCategory.TESTABILITY,
                            severity=Severity.MEDIUM,
                            line_number=node.lineno,
                            symbol_name=node.name,
                            description=f"Function '{node.name}' has {param_count} parameters",
                            suggestion="Consider using a parameter object or builder pattern",
                            metrics={"param_count": param_count},
                        )
                    )
                    score -= 5

                # Global state has to be set up and torn down
                globals_used = self._find_global_usage(node)
                if globals_used:
                    issues.append(
                        QualityIssue(
                            category=IssueCategory.TESTABILITY,
                            severity=Severity.MEDIUM,
                            line_number=node.lineno,
                            symbol_name=node.name,
                            description=(
                                f"Function '{node.name}' uses global variables: {', '.join(globals_used)}"
                            ),
                            suggestion="Pass globals as parameters to improve testability",
                            metrics={"globals": globals_used},
                        )
                    )
                    score -= 10

            elif isinstance(node, ast.ClassDef):
                # A singleton cannot be replaced in a test
                if self._is_singleton(node):
                    issues.append(
                        QualityIssue(
                            category=IssueCategory.TESTABILITY,
                            severity=Severity.LOW,
                            line_number=node.lineno,
                            symbol_name=node.name,
                            description=f"Class '{node.name}' appears to be a Singleton",
                            suggestion=("Consider using dependency injection instead for better testability"),
                            metrics={},
                        )
                    )
                    score -= 5

        return TestabilityScore(
            score=max(0, score), issues=issues, summary=f"Testability score: {max(0, score)}/100"
        )

    def _find_global_usage(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """The globals a function declares it will write to."""
        globals_used = []

        for stmt in func_node.body:
            if isinstance(stmt, ast.Global):
                globals_used.extend(stmt.names)

        return globals_used

    def _is_singleton(self, class_node: ast.ClassDef) -> bool:
        """True when the class looks like a singleton."""
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name in ["get_instance", "getInstance", "instance"]:
                    return True
                if item.name == "__new__":
                    return True
        return False

    def check_error_handling(self, tree: ast.AST) -> ErrorHandlingReport:
        """Checks how failure is handled."""
        report = ErrorHandlingReport()

        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                report.try_catch_count += 1

                for handler in node.handlers:
                    # An empty handler discards the reason
                    if self._is_empty_handler(handler):
                        report.empty_catches += 1
                        report.issues.append(
                            QualityIssue(
                                category=IssueCategory.ERROR_HANDLING,
                                severity=Severity.HIGH,
                                line_number=handler.lineno,
                                symbol_name="except",
                                description="Empty except block silently swallows errors",
                                suggestion=(
                                    "At minimum, log the error. Consider re-raising or handling properly."
                                ),
                                metrics={},
                            )
                        )

                    # A bare or overly broad handler catches too much
                    if handler.type is None:
                        report.generic_exceptions += 1
                        report.issues.append(
                            QualityIssue(
                                category=IssueCategory.ERROR_HANDLING,
                                severity=Severity.MEDIUM,
                                line_number=handler.lineno,
                                symbol_name="except",
                                description=(
                                    "Bare 'except:' catches all exceptions including KeyboardInterrupt"
                                ),
                                suggestion=(
                                    "Specify expected exception types: except (ValueError, TypeError):"
                                ),
                                metrics={},
                            )
                        )
                    elif isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                        report.generic_exceptions += 1
                        report.issues.append(
                            QualityIssue(
                                category=IssueCategory.ERROR_HANDLING,
                                severity=Severity.LOW,
                                line_number=handler.lineno,
                                symbol_name="except Exception",
                                description="Catching generic 'Exception' may hide bugs",
                                suggestion="Catch specific exception types when possible",
                                metrics={},
                            )
                        )

                # A resource acquired in a try wants a finally or a with
                if not node.finalbody and self._has_resource_management(node):
                    report.missing_finally += 1
                    report.issues.append(
                        QualityIssue(
                            category=IssueCategory.ERROR_HANDLING,
                            severity=Severity.MEDIUM,
                            line_number=node.lineno,
                            symbol_name="try",
                            description="Try block with resource management but no finally clause",
                            suggestion=(
                                "Add finally block for cleanup or use context manager (with statement)"
                            ),
                            metrics={},
                        )
                    )

        return report

    def _is_empty_handler(self, handler: ast.ExceptHandler) -> bool:
        """True when the handler does nothing with the exception."""
        if len(handler.body) == 0:
            return True
        if len(handler.body) == 1:
            stmt = handler.body[0]
            if isinstance(stmt, ast.Pass):
                return True
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                return True  # Sadece docstring
        return False

    def _has_resource_management(self, try_node: ast.Try) -> bool:
        """True when the try block acquires something that needs releasing.

        A resource acquired by a `with` does **not** count. The whole purpose of
        a context manager is that release is already arranged, so demanding a
        `finally` beside one is demanding the thing that made `finally`
        unnecessary — and the suggestion a reader gets is to add code that does
        nothing.

        Found by Level 28: the new `bare_except` case reported this on
        `with open(...) as handle:` inside a `try`, twice, and the corpus is what
        turned it from behaviour nobody had looked at into a defect.
        """
        resource_patterns = ["open", "connect", "acquire", "lock", "socket"]

        managed = {
            id(item.context_expr)
            for statement in ast.walk(try_node)
            if isinstance(statement, (ast.With, ast.AsyncWith))
            for item in statement.items
        }

        for stmt in ast.walk(try_node):
            if not isinstance(stmt, ast.Call) or id(stmt) in managed:
                continue
            if isinstance(stmt.func, ast.Name):
                if any(p in stmt.func.id.lower() for p in resource_patterns):
                    return True
            elif isinstance(stmt.func, ast.Attribute) and any(
                p in stmt.func.attr.lower() for p in resource_patterns
            ):
                return True
        return False

    def _collect_all_issues(self, report: QualityReport) -> list[QualityIssue]:
        """Folds every sub-report into one issue list."""
        issues = []

        issues.extend(report.solid_report.srp_issues)
        issues.extend(report.solid_report.ocp_issues)
        issues.extend(report.solid_report.lsp_issues)
        issues.extend(report.solid_report.isp_issues)
        issues.extend(report.solid_report.dip_issues)

        if report.testability:
            issues.extend(report.testability.issues)

        if report.error_handling:
            issues.extend(report.error_handling.issues)

        # Duplication, once per repeated block
        for dup in report.duplicates:
            if len(dup.locations) > 1:
                issues.append(
                    QualityIssue(
                        category=IssueCategory.DRY,
                        severity=Severity.MEDIUM,
                        line_number=dup.locations[0][0],
                        symbol_name="duplicate",
                        description=f"Duplicate code block found at {len(dup.locations)} locations",
                        suggestion="Extract common code into a reusable function",
                        metrics={"locations": dup.locations},
                    )
                )

        return issues

    def _calculate_quality_score(self, report: QualityReport) -> int:
        """Reduces the issues to a score out of 100."""
        score = 100

        # Each issue costs according to how much it matters
        for issue in report.all_issues:
            if issue.severity == Severity.HIGH:
                score -= 10
            elif issue.severity == Severity.MEDIUM:
                score -= 5
            elif issue.severity == Severity.LOW:
                score -= 2

        return max(0, score)

    def _generate_summary(self, report: QualityReport) -> str:
        """A short summary a reviewer reads before the issue list."""
        parts = []

        score = report.quality_score
        if score >= 90:
            emoji = "🟢"
            grade = "Excellent"
        elif score >= 70:
            emoji = "🟡"
            grade = "Good"
        elif score >= 50:
            emoji = "🟠"
            grade = "Needs Improvement"
        else:
            emoji = "🔴"
            grade = "Poor"

        parts.append(f"{emoji} **Quality Score**: {score}/100 ({grade})")

        # SOLID issues
        solid_total = report.solid_report.total_issues()
        if solid_total:
            parts.append(f"\n**SOLID Violations**: {solid_total}")
            if report.solid_report.srp_issues:
                parts.append(f"  - SRP: {len(report.solid_report.srp_issues)}")
            if report.solid_report.dip_issues:
                parts.append(f"  - DIP: {len(report.solid_report.dip_issues)}")
            if report.solid_report.isp_issues:
                parts.append(f"  - ISP: {len(report.solid_report.isp_issues)}")

        # Duplicates
        if report.duplicates:
            parts.append(f"\n**Duplicate Code Blocks**: {len(report.duplicates)}")

        # Testability
        if report.testability:
            parts.append(f"\n**Testability Score**: {report.testability.score}/100")

        # Error handling
        if report.error_handling:
            eh = report.error_handling
            if eh.empty_catches or eh.generic_exceptions:
                parts.append("\n**Error Handling Issues**:")
                if eh.empty_catches:
                    parts.append(f"  - Empty catches: {eh.empty_catches}")
                if eh.generic_exceptions:
                    parts.append(f"  - Generic exceptions: {eh.generic_exceptions}")

        return "\n".join(parts)


def check_code_quality(content: str, file_path: str = "", policy: QualityPolicy | None = None) -> str:
    """
    Runs the analysis and renders it as markdown, for the agent's tool call.

    Args:
        content: The file's text.
        file_path: Used to decide whether an AST pass is possible.
        policy: Thresholds to apply; the defaults are used without one.

    Returns:
        The report as markdown.
    """
    analyzer = QualityAnalyzer(policy)
    report = analyzer.analyze(content, file_path)

    output = [f"## 📊 Code Quality Analysis: `{file_path or 'Code'}`\n"]
    output.append(report.summary)

    if report.all_issues:
        output.append("\n### Quality Issues:\n")

        # Most severe first: the truncation below must not drop them
        sorted_issues = sorted(report.all_issues, key=lambda issue: issue.severity)

        for issue in sorted_issues[:15]:  # Max 15 issue
            severity_icon = {
                Severity.HIGH: "🔴",
                Severity.MEDIUM: "🟡",
                Severity.LOW: "🟢",
                Severity.INFO: "ℹ️",
            }

            output.append(
                f"#### {severity_icon.get(issue.severity, '')} "
                f"Line {issue.line_number}: {issue.category.value}"
            )
            output.append(f"**Symbol**: `{issue.symbol_name}`")
            output.append(f"**Issue**: {issue.description}")
            output.append(f"**Fix**: {issue.suggestion}\n")

    return "\n".join(output)
