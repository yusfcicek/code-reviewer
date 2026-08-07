"""
Performance Analyzer - Performans ve Kaynak Kullanım Analizi.

Big-O kompleksite analizi ve potansiyel performans sorunlarını tespit eder:
- O(n²) ve daha kötü kompleksite tespiti
- Memory leak pattern'leri
- N+1 query pattern
- Gereksiz bellek kopyaları
- Resource leak kontrolü
"""

import ast
import re
from dataclasses import dataclass, field
from enum import Enum

from code_reviewer.domain.policy import PerformancePolicy
from code_reviewer.domain.severity import Severity


class PerformanceIssueType(Enum):
    """Performans sorunu tipleri."""

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
    """Performans sorunu."""

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
    """Kompleksite raporu."""

    function_name: str
    estimated_complexity: str
    nested_loops: int
    recursive: bool
    issues: list[PerformanceIssue] = field(default_factory=list)


@dataclass
class MemoryLeakRisk:
    """Memory leak riski."""

    line_number: int
    resource_type: str  # "file", "connection", "socket", etc.
    description: str
    suggestion: str


@dataclass
class NPlusOnePattern:
    """N+1 query pattern."""

    loop_line: int
    query_line: int
    description: str
    suggestion: str


@dataclass
class PerformanceReport:
    """Performans analiz raporu."""

    file_path: str
    issues: list[PerformanceIssue] = field(default_factory=list)
    complexity_reports: list[ComplexityReport] = field(default_factory=list)
    memory_leak_risks: list[MemoryLeakRisk] = field(default_factory=list)
    n_plus_one_patterns: list[NPlusOnePattern] = field(default_factory=list)
    performance_score: int = 100
    summary: str = ""


class PerformanceAnalyzer:
    """
    Big-O kompleksite ve memory leak analizi.

    Analiz kapsamı:
    - Nested loop tespiti (O(n²), O(n³))
    - Recursive çağrı analizi
    - Büyük veri üzerinde iterasyon
    - Kapatılmayan resource'lar
    - N+1 query pattern'leri
    """

    # Kaynak yönetimi gerektiren fonksiyonlar
    RESOURCE_OPENERS = {
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

    # Kaynak temizleyicileri
    RESOURCE_CLOSERS = {"close", "release", "disconnect", "shutdown"}

    # Database/API çağrıları
    DB_QUERY_PATTERNS = [
        r"\.execute\s*\(",
        r"\.query\s*\(",
        r"\.find\s*\(",
        r"\.get\s*\(",
        r"\.filter\s*\(",
        r"\.all\s*\(",
        r"requests\.\w+\s*\(",
        r"\.fetch\s*\(",
        r"\.select\s*\(",
    ]

    # Büyük bellek kullanımı pattern'leri
    LARGE_MEMORY_PATTERNS = [
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
        Kapsamlı performans analizi yapar.

        Args:
            content: Dosya içeriği
            file_path: Dosya yolu

        Returns:
            PerformanceReport: Analiz sonucu
        """
        report = PerformanceReport(file_path=file_path)

        # Python için AST analizi
        if file_path.endswith(".py"):
            try:
                tree = ast.parse(content)

                # Complexity analizi
                report.complexity_reports = self._analyze_complexity(tree)

                # Memory leak riskleri
                if self.alert_on_memory_leak:
                    report.memory_leak_risks = self._detect_memory_leaks(tree)

                # N+1 pattern
                if self.alert_on_n_plus_one:
                    report.n_plus_one_patterns = self._detect_n_plus_one(tree, content)

                # Quadratic string building
                report.issues.extend(self._detect_string_concat_in_loop(tree))

            except SyntaxError:
                pass

        # Regex tabanlı analizler (tüm diller)
        report.issues.extend(self._analyze_patterns(content))

        # Issues'ları topla
        report.issues.extend(self._collect_issues(report))

        # Performans skoru
        report.performance_score = self._calculate_score(report)

        # Özet
        report.summary = self._generate_summary(report)

        return report

    def _analyze_complexity(self, tree: ast.AST) -> list[ComplexityReport]:
        """Fonksiyon kompleksitelerini analiz eder."""
        reports = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                report = self._analyze_function_complexity(node)
                if report.nested_loops > 0 or report.recursive:
                    reports.append(report)

        return reports

    def _analyze_function_complexity(self, func_node: ast.FunctionDef) -> ComplexityReport:
        """Tek fonksiyonun kompleksitesini analiz eder."""
        max_depth = 0
        is_recursive = False

        # Nested loop derinliği
        max_depth = self._find_max_loop_depth(func_node)

        # Recursive çağrı kontrolü
        is_recursive = self._is_recursive(func_node)

        # Tahmini kompleksite
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

        # Uyarılar ekle
        if self.alert_on_n_squared and max_depth >= self.max_nested_loops:
            report.issues.append(
                PerformanceIssue(
                    issue_type=PerformanceIssueType.HIGH_COMPLEXITY,
                    severity=Severity.HIGH
                    if max_depth > self.max_nested_loops
                    else Severity.MEDIUM,
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
        """Maximum nested loop derinliğini bulur."""
        max_depth = current_depth

        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                child_depth = self._find_max_loop_depth(child, current_depth + 1)
                max_depth = max(max_depth, child_depth)
            elif isinstance(child, ast.comprehension):
                # List/dict comprehension da döngü sayılır
                child_depth = self._find_max_loop_depth(child, current_depth + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = self._find_max_loop_depth(child, current_depth)
                max_depth = max(max_depth, child_depth)

        return max_depth

    def _is_recursive(self, func_node: ast.FunctionDef) -> bool:
        """Fonksiyonun recursive olup olmadığını kontrol eder."""
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
        """Memory leak risklerini tespit eder."""
        risks = []

        for node in ast.walk(tree):
            # open() without context manager
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(node.value, ast.Call):
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
        """Kaynak atamasını kontrol eder."""
        call = node.value
        if not isinstance(call, ast.Call):
            return

        func_name = self._get_call_name(call)

        if func_name in self.RESOURCE_OPENERS:
            # with statement içinde mi kontrol et
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
        """Kapatılmamış kaynakları tespit eder."""
        risks = []
        opened_resources: dict[str, int] = {}  # var_name -> line_number

        for node in ast.walk(tree):
            # Kaynak açma
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    func_name = self._get_call_name(node.value)
                    if func_name in self.RESOURCE_OPENERS:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                opened_resources[target.id] = node.lineno

            # Kaynak kapatma
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr in self.RESOURCE_CLOSERS:
                        if isinstance(node.func.value, ast.Name):
                            var_name = node.func.value.id
                            opened_resources.pop(var_name, None)

        # Kapatılmamış kaynaklar
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
        """Çağrı adını döner."""
        if isinstance(call.func, ast.Name):
            return call.func.id
        elif isinstance(call.func, ast.Attribute):
            return call.func.attr
        return ""

    def _detect_n_plus_one(self, tree: ast.AST, content: str) -> list[NPlusOnePattern]:
        """N+1 query pattern'lerini tespit eder."""
        patterns = []
        lines = content.split("\n")

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                loop_line = node.lineno

                # Loop içinde DB/API çağrısı var mı?
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        call_name = self._get_call_name(child)
                        if hasattr(child, "lineno"):
                            call_line_content = (
                                lines[child.lineno - 1] if child.lineno <= len(lines) else ""
                            )

                            for pattern in self.DB_QUERY_PATTERNS:
                                if re.search(pattern, call_line_content):
                                    patterns.append(
                                        NPlusOnePattern(
                                            loop_line=loop_line,
                                            query_line=child.lineno,
                                            description=f"Database/API call inside loop at line {child.lineno}",
                                            suggestion="Batch the queries: fetch all data before the loop or use eager loading",
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
                            f"String concatenation with += inside a loop "
                            f"(line {child.lineno}) is O(n²)"
                        ),
                        suggestion="Collect the parts in a list and ''.join(...) once, or use io.StringIO",
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
        """Regex tabanlı performans pattern'lerini analiz eder."""
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
        """Tüm performans sorunlarını toplar."""
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
        """Performans skoru hesaplar."""
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
        """Performans özeti oluşturur."""
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

        # Complexity summary
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
        issue_types = {}
        for issue in report.issues:
            issue_types[issue.issue_type.value] = issue_types.get(issue.issue_type.value, 0) + 1

        if issue_types:
            parts.append("\n**Issue Breakdown**:")
            for itype, count in sorted(issue_types.items(), key=lambda x: -x[1]):
                parts.append(f"  - {itype}: {count}")

        return "\n".join(parts)


def analyze_performance(
    content: str, file_path: str = "", policy: PerformancePolicy | None = None
) -> str:
    """
    Tool wrapper - Performans analizi yapar.

    Args:
        content: Dosya içeriği
        file_path: Dosya yolu

    Returns:
        Formatlanmış performans raporu
    """
    analyzer = PerformanceAnalyzer(policy)
    report = analyzer.analyze(content, file_path)

    output = [f"## ⚡ Performance Analysis: `{file_path or 'Code'}`\n"]
    output.append(report.summary)

    if report.issues:
        output.append("\n### Performance Issues:\n")

        # Severity'ye göre sırala
        sorted_issues = sorted(report.issues, key=lambda issue: issue.severity)

        for issue in sorted_issues[:15]:  # Max 15 issue
            severity_icon = {
                Severity.CRITICAL: "🔴",
                Severity.HIGH: "🟠",
                Severity.MEDIUM: "🟡",
                Severity.LOW: "🟢",
            }

            output.append(
                f"#### {severity_icon.get(issue.severity, '')} Line {issue.line_number}: {issue.issue_type.value}"
            )
            if issue.complexity:
                output.append(f"**Complexity**: {issue.complexity}")
            output.append(f"**Issue**: {issue.description}")
            output.append(f"**Fix**: {issue.suggestion}\n")

    return "\n".join(output)
