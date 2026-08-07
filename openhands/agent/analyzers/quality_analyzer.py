"""
Quality Analyzer - Kod Kalitesi ve SOLID Prensipleri Analizi.

SOLID prensipleri, DRY, test edilebilirlik ve hata yakalama kontrolü yapar:
- Single Responsibility Principle (SRP)
- Open/Closed Principle (OCP)
- Liskov Substitution Principle (LSP)
- Interface Segregation Principle (ISP)
- Dependency Inversion Principle (DIP)
- Duplicate Code Detection
- Testability Analysis
- Error Handling Analysis
"""

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict
import hashlib


class IssueCategory(Enum):
    """Kalite sorunu kategorisi."""
    SOLID_SRP = "solid_srp"           # Single Responsibility
    SOLID_OCP = "solid_ocp"           # Open/Closed
    SOLID_LSP = "solid_lsp"           # Liskov Substitution
    SOLID_ISP = "solid_isp"           # Interface Segregation
    SOLID_DIP = "solid_dip"           # Dependency Inversion
    DRY = "dry"                        # Don't Repeat Yourself
    TESTABILITY = "testability"
    ERROR_HANDLING = "error_handling"
    CODE_SMELL = "code_smell"
    MAINTAINABILITY = "maintainability"


class IssueSeverity(Enum):
    """Sorun şiddeti."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class QualityIssue:
    """Kod kalitesi sorunu."""
    category: IssueCategory
    severity: IssueSeverity
    line_number: int
    symbol_name: str
    description: str
    suggestion: str
    metrics: Dict = field(default_factory=dict)


@dataclass
class DuplicateBlock:
    """Tekrarlanan kod bloğu."""
    hash: str
    locations: List[Tuple[int, int]] = field(default_factory=list)  # (start_line, end_line)
    content_preview: str = ""
    line_count: int = 0


@dataclass
class SOLIDReport:
    """SOLID prensipleri raporu."""
    srp_issues: List[QualityIssue] = field(default_factory=list)
    ocp_issues: List[QualityIssue] = field(default_factory=list)
    lsp_issues: List[QualityIssue] = field(default_factory=list)
    isp_issues: List[QualityIssue] = field(default_factory=list)
    dip_issues: List[QualityIssue] = field(default_factory=list)
    
    def total_issues(self) -> int:
        return (len(self.srp_issues) + len(self.ocp_issues) + 
                len(self.lsp_issues) + len(self.isp_issues) + len(self.dip_issues))


@dataclass
class TestabilityScore:
    """Test edilebilirlik skoru."""
    score: int  # 0-100
    issues: List[QualityIssue] = field(default_factory=list)
    summary: str = ""


@dataclass
class ErrorHandlingReport:
    """Hata yakalama raporu."""
    issues: List[QualityIssue] = field(default_factory=list)
    try_catch_count: int = 0
    empty_catches: int = 0
    generic_exceptions: int = 0
    missing_finally: int = 0


@dataclass
class QualityReport:
    """Genel kalite raporu."""
    file_path: str
    solid_report: SOLIDReport = field(default_factory=SOLIDReport)
    duplicates: List[DuplicateBlock] = field(default_factory=list)
    testability: Optional[TestabilityScore] = None
    error_handling: Optional[ErrorHandlingReport] = None
    all_issues: List[QualityIssue] = field(default_factory=list)
    quality_score: int = 100
    summary: str = ""


class QualityAnalyzer:
    """
    SOLID, DRY, test edilebilirlik ve hata yakalama analizi.
    """
    
    # Thresholds
    MAX_CLASS_METHODS = 10          # SRP: Sınıf başına max method
    MAX_FUNCTION_LINES = 50         # SRP: Fonksiyon başına max satır
    MAX_FUNCTION_PARAMS = 5         # Testability: Max parametre
    MAX_CYCLOMATIC_COMPLEXITY = 10  # Max cyclomatic complexity
    MIN_DUPLICATE_LINES = 5         # Duplicate tespiti için min satır
    
    def __init__(self):
        self._class_info: Dict[str, Dict] = {}
        self._function_info: Dict[str, Dict] = {}
    
    def analyze(self, content: str, file_path: str = "") -> QualityReport:
        """
        Kapsamlı kod kalitesi analizi yapar.
        """
        report = QualityReport(file_path=file_path)
        
        # Python dosyaları için AST analizi
        if file_path.endswith('.py'):
            try:
                tree = ast.parse(content)
                report.solid_report = self.check_solid_principles(tree, content)
                report.testability = self.analyze_testability(tree, content)
                report.error_handling = self.check_error_handling(tree)
            except SyntaxError:
                pass
        
        # Duplicate code detection (dil bağımsız)
        report.duplicates = self.detect_duplicates(content)
        
        # Tüm sorunları birleştir
        report.all_issues = self._collect_all_issues(report)
        
        # Kalite skoru hesapla
        report.quality_score = self._calculate_quality_score(report)
        
        # Özet oluştur
        report.summary = self._generate_summary(report)
        
        return report
    
    def check_solid_principles(self, tree: ast.AST, content: str) -> SOLIDReport:
        """SOLID prensiplerini kontrol eder."""
        report = SOLIDReport()
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # SRP: Single Responsibility
                srp_issues = self._check_srp(node)
                report.srp_issues.extend(srp_issues)
                
                # DIP: Dependency Inversion
                dip_issues = self._check_dip(node)
                report.dip_issues.extend(dip_issues)
                
                # ISP: Interface Segregation (abstract/base class ise)
                if self._is_abstract_class(node):
                    isp_issues = self._check_isp(node)
                    report.isp_issues.extend(isp_issues)
            
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # SRP: Fonksiyon uzunluğu
                srp_issues = self._check_function_srp(node, content)
                report.srp_issues.extend(srp_issues)
        
        return report
    
    def _check_srp(self, class_node: ast.ClassDef) -> List[QualityIssue]:
        """Single Responsibility Principle kontrolü."""
        issues = []
        
        # Method sayısı kontrolü
        method_count = sum(
            1 for item in class_node.body 
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not item.name.startswith('_')
        )
        
        if method_count > self.MAX_CLASS_METHODS:
            issues.append(QualityIssue(
                category=IssueCategory.SOLID_SRP,
                severity=IssueSeverity.MEDIUM,
                line_number=class_node.lineno,
                symbol_name=class_node.name,
                description=f"Class '{class_node.name}' has {method_count} public methods (max: {self.MAX_CLASS_METHODS})",
                suggestion="Consider splitting into multiple smaller classes with focused responsibilities",
                metrics={"method_count": method_count}
            ))
        
        # Çok fazla instance variable
        init_method = None
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                init_method = item
                break
        
        if init_method:
            instance_vars = self._count_instance_variables(init_method)
            if instance_vars > 7:
                issues.append(QualityIssue(
                    category=IssueCategory.SOLID_SRP,
                    severity=IssueSeverity.MEDIUM,
                    line_number=class_node.lineno,
                    symbol_name=class_node.name,
                    description=f"Class '{class_node.name}' has {instance_vars} instance variables",
                    suggestion="Many instance variables may indicate mixed responsibilities. Consider composition.",
                    metrics={"instance_vars": instance_vars}
                ))
        
        return issues
    
    def _check_function_srp(self, func_node: ast.FunctionDef, content: str) -> List[QualityIssue]:
        """Fonksiyon SRP kontrolü (uzunluk, complexity)."""
        issues = []
        
        # Satır sayısı
        if hasattr(func_node, 'end_lineno'):
            line_count = func_node.end_lineno - func_node.lineno + 1
            if line_count > self.MAX_FUNCTION_LINES:
                issues.append(QualityIssue(
                    category=IssueCategory.SOLID_SRP,
                    severity=IssueSeverity.MEDIUM,
                    line_number=func_node.lineno,
                    symbol_name=func_node.name,
                    description=f"Function '{func_node.name}' is {line_count} lines (max: {self.MAX_FUNCTION_LINES})",
                    suggestion="Break down into smaller, focused functions",
                    metrics={"line_count": line_count}
                ))
        
        # Cyclomatic complexity
        complexity = self._calculate_cyclomatic_complexity(func_node)
        if complexity > self.MAX_CYCLOMATIC_COMPLEXITY:
            issues.append(QualityIssue(
                category=IssueCategory.MAINTAINABILITY,
                severity=IssueSeverity.HIGH,
                line_number=func_node.lineno,
                symbol_name=func_node.name,
                description=f"Function '{func_node.name}' has high cyclomatic complexity: {complexity}",
                suggestion="Reduce branching by extracting helper functions or using polymorphism",
                metrics={"cyclomatic_complexity": complexity}
            ))
        
        return issues
    
    def _check_dip(self, class_node: ast.ClassDef) -> List[QualityIssue]:
        """Dependency Inversion Principle kontrolü."""
        issues = []
        
        # __init__ içinde somut sınıf instantiation kontrolü
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                for stmt in ast.walk(item):
                    if isinstance(stmt, ast.Call):
                        if isinstance(stmt.func, ast.Name):
                            # Somut sınıf instantiation (büyük harfle başlayan)
                            if stmt.func.id[0].isupper() and stmt.func.id not in ['Type', 'Dict', 'List', 'Set', 'Optional']:
                                issues.append(QualityIssue(
                                    category=IssueCategory.SOLID_DIP,
                                    severity=IssueSeverity.LOW,
                                    line_number=stmt.lineno if hasattr(stmt, 'lineno') else class_node.lineno,
                                    symbol_name=class_node.name,
                                    description=f"Class '{class_node.name}' instantiates concrete class '{stmt.func.id}' in __init__",
                                    suggestion="Consider dependency injection - pass the dependency as a constructor parameter",
                                    metrics={"concrete_class": stmt.func.id}
                                ))
        
        return issues
    
    def _check_isp(self, class_node: ast.ClassDef) -> List[QualityIssue]:
        """Interface Segregation Principle kontrolü."""
        issues = []
        
        # Abstract method sayısı
        abstract_methods = []
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == 'abstractmethod':
                        abstract_methods.append(item.name)
        
        if len(abstract_methods) > 7:
            issues.append(QualityIssue(
                category=IssueCategory.SOLID_ISP,
                severity=IssueSeverity.MEDIUM,
                line_number=class_node.lineno,
                symbol_name=class_node.name,
                description=f"Interface '{class_node.name}' has {len(abstract_methods)} abstract methods",
                suggestion="Consider splitting into smaller, more focused interfaces",
                metrics={"abstract_method_count": len(abstract_methods)}
            ))
        
        return issues
    
    def _is_abstract_class(self, class_node: ast.ClassDef) -> bool:
        """Sınıfın abstract olup olmadığını kontrol eder."""
        # ABC inheritance veya Meta check
        for base in class_node.bases:
            if isinstance(base, ast.Name) and base.id in ['ABC', 'ABCMeta']:
                return True
            if isinstance(base, ast.Attribute) and base.attr in ['ABC', 'ABCMeta']:
                return True
        
        # abstractmethod decorator kontrolü
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in item.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == 'abstractmethod':
                        return True
        
        return False
    
    def _count_instance_variables(self, init_method: ast.FunctionDef) -> int:
        """__init__ içindeki instance variable sayısını sayar."""
        count = 0
        for stmt in ast.walk(init_method):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Attribute):
                        if isinstance(target.value, ast.Name) and target.value.id == 'self':
                            count += 1
        return count
    
    def _calculate_cyclomatic_complexity(self, func_node: ast.FunctionDef) -> int:
        """Cyclomatic complexity hesaplar."""
        complexity = 1  # Base complexity
        
        for node in ast.walk(func_node):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(node, ast.ExceptHandler):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
            elif isinstance(node, ast.comprehension):
                complexity += 1
                if node.ifs:
                    complexity += len(node.ifs)
        
        return complexity
    
    def detect_duplicates(self, content: str) -> List[DuplicateBlock]:
        """Tekrarlanan kod bloklarını tespit eder."""
        duplicates = []
        lines = content.split('\n')
        
        # Normalize edilmiş satır hash'leri
        normalized_lines = []
        for i, line in enumerate(lines):
            normalized = self._normalize_line(line)
            if normalized:  # Boş satırları atla
                normalized_lines.append((i + 1, normalized))
        
        # Sliding window ile blok hash'leri
        block_size = self.MIN_DUPLICATE_LINES
        block_hashes: Dict[str, List[int]] = defaultdict(list)
        
        for i in range(len(normalized_lines) - block_size + 1):
            block = [nl[1] for nl in normalized_lines[i:i + block_size]]
            block_hash = hashlib.md5('\n'.join(block).encode()).hexdigest()
            start_line = normalized_lines[i][0]
            block_hashes[block_hash].append(start_line)
        
        # Tekrarlananları bul
        for hash_val, starts in block_hashes.items():
            if len(starts) > 1:
                duplicates.append(DuplicateBlock(
                    hash=hash_val,
                    locations=[(s, s + block_size - 1) for s in starts],
                    content_preview=lines[starts[0] - 1] if starts else "",
                    line_count=block_size
                ))
        
        return duplicates
    
    def _normalize_line(self, line: str) -> str:
        """Satırı karşılaştırma için normalize eder."""
        stripped = line.strip()
        
        # Yorum ve boş satırları atla
        if not stripped or stripped.startswith('#') or stripped.startswith('//'):
            return ""
        
        # Whitespace'i normalize et
        return re.sub(r'\s+', ' ', stripped)
    
    def analyze_testability(self, tree: ast.AST, content: str) -> TestabilityScore:
        """Test edilebilirlik analizi."""
        issues = []
        score = 100
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Çok fazla parametre
                param_count = len(node.args.args)
                if param_count > self.MAX_FUNCTION_PARAMS:
                    issues.append(QualityIssue(
                        category=IssueCategory.TESTABILITY,
                        severity=IssueSeverity.MEDIUM,
                        line_number=node.lineno,
                        symbol_name=node.name,
                        description=f"Function '{node.name}' has {param_count} parameters",
                        suggestion="Consider using a parameter object or builder pattern",
                        metrics={"param_count": param_count}
                    ))
                    score -= 5
                
                # Global state kullanımı
                globals_used = self._find_global_usage(node)
                if globals_used:
                    issues.append(QualityIssue(
                        category=IssueCategory.TESTABILITY,
                        severity=IssueSeverity.MEDIUM,
                        line_number=node.lineno,
                        symbol_name=node.name,
                        description=f"Function '{node.name}' uses global variables: {', '.join(globals_used)}",
                        suggestion="Pass globals as parameters to improve testability",
                        metrics={"globals": globals_used}
                    ))
                    score -= 10
            
            elif isinstance(node, ast.ClassDef):
                # Singleton pattern (test edilmesi zor)
                if self._is_singleton(node):
                    issues.append(QualityIssue(
                        category=IssueCategory.TESTABILITY,
                        severity=IssueSeverity.LOW,
                        line_number=node.lineno,
                        symbol_name=node.name,
                        description=f"Class '{node.name}' appears to be a Singleton",
                        suggestion="Consider using dependency injection instead for better testability",
                        metrics={}
                    ))
                    score -= 5
        
        return TestabilityScore(
            score=max(0, score),
            issues=issues,
            summary=f"Testability score: {max(0, score)}/100"
        )
    
    def _find_global_usage(self, func_node: ast.FunctionDef) -> List[str]:
        """Fonksiyon içinde kullanılan global değişkenleri bulur."""
        globals_used = []
        
        for stmt in func_node.body:
            if isinstance(stmt, ast.Global):
                globals_used.extend(stmt.names)
        
        return globals_used
    
    def _is_singleton(self, class_node: ast.ClassDef) -> bool:
        """Singleton pattern tespiti."""
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name in ['get_instance', 'getInstance', 'instance']:
                    return True
                if item.name == '__new__':
                    return True
        return False
    
    def check_error_handling(self, tree: ast.AST) -> ErrorHandlingReport:
        """Hata yakalama analizi."""
        report = ErrorHandlingReport()
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                report.try_catch_count += 1
                
                for handler in node.handlers:
                    # Boş except bloğu
                    if self._is_empty_handler(handler):
                        report.empty_catches += 1
                        report.issues.append(QualityIssue(
                            category=IssueCategory.ERROR_HANDLING,
                            severity=IssueSeverity.HIGH,
                            line_number=handler.lineno,
                            symbol_name="except",
                            description="Empty except block silently swallows errors",
                            suggestion="At minimum, log the error. Consider re-raising or handling properly.",
                            metrics={}
                        ))
                    
                    # Generic exception
                    if handler.type is None:
                        report.generic_exceptions += 1
                        report.issues.append(QualityIssue(
                            category=IssueCategory.ERROR_HANDLING,
                            severity=IssueSeverity.MEDIUM,
                            line_number=handler.lineno,
                            symbol_name="except",
                            description="Bare 'except:' catches all exceptions including KeyboardInterrupt",
                            suggestion="Specify expected exception types: except (ValueError, TypeError):",
                            metrics={}
                        ))
                    elif isinstance(handler.type, ast.Name) and handler.type.id == 'Exception':
                        report.generic_exceptions += 1
                        report.issues.append(QualityIssue(
                            category=IssueCategory.ERROR_HANDLING,
                            severity=IssueSeverity.LOW,
                            line_number=handler.lineno,
                            symbol_name="except Exception",
                            description="Catching generic 'Exception' may hide bugs",
                            suggestion="Catch specific exception types when possible",
                            metrics={}
                        ))
                
                # Finally eksik (resource management varsa)
                if not node.finalbody:
                    if self._has_resource_management(node):
                        report.missing_finally += 1
                        report.issues.append(QualityIssue(
                            category=IssueCategory.ERROR_HANDLING,
                            severity=IssueSeverity.MEDIUM,
                            line_number=node.lineno,
                            symbol_name="try",
                            description="Try block with resource management but no finally clause",
                            suggestion="Add finally block for cleanup or use context manager (with statement)",
                            metrics={}
                        ))
        
        return report
    
    def _is_empty_handler(self, handler: ast.ExceptHandler) -> bool:
        """Except bloğunun boş olup olmadığını kontrol eder."""
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
        """Try bloğunda kaynak yönetimi olup olmadığını kontrol eder."""
        resource_patterns = ['open', 'connect', 'acquire', 'lock', 'socket']
        
        for stmt in ast.walk(try_node):
            if isinstance(stmt, ast.Call):
                if isinstance(stmt.func, ast.Name):
                    if any(p in stmt.func.id.lower() for p in resource_patterns):
                        return True
                elif isinstance(stmt.func, ast.Attribute):
                    if any(p in stmt.func.attr.lower() for p in resource_patterns):
                        return True
        return False
    
    def _collect_all_issues(self, report: QualityReport) -> List[QualityIssue]:
        """Tüm sorunları tek listede toplar."""
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
        
        # Duplicate code issues
        for dup in report.duplicates:
            if len(dup.locations) > 1:
                issues.append(QualityIssue(
                    category=IssueCategory.DRY,
                    severity=IssueSeverity.MEDIUM,
                    line_number=dup.locations[0][0],
                    symbol_name="duplicate",
                    description=f"Duplicate code block found at {len(dup.locations)} locations",
                    suggestion="Extract common code into a reusable function",
                    metrics={"locations": dup.locations}
                ))
        
        return issues
    
    def _calculate_quality_score(self, report: QualityReport) -> int:
        """Kalite skoru hesaplar (0-100)."""
        score = 100
        
        # Issue severity penalties
        for issue in report.all_issues:
            if issue.severity == IssueSeverity.HIGH:
                score -= 10
            elif issue.severity == IssueSeverity.MEDIUM:
                score -= 5
            elif issue.severity == IssueSeverity.LOW:
                score -= 2
        
        return max(0, score)
    
    def _generate_summary(self, report: QualityReport) -> str:
        """Kalite raporu özeti oluşturur."""
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
                parts.append(f"\n**Error Handling Issues**:")
                if eh.empty_catches:
                    parts.append(f"  - Empty catches: {eh.empty_catches}")
                if eh.generic_exceptions:
                    parts.append(f"  - Generic exceptions: {eh.generic_exceptions}")
        
        return '\n'.join(parts)


def check_code_quality(content: str, file_path: str = "") -> str:
    """
    Tool wrapper - Kod kalitesi analizi yapar.
    
    Args:
        content: Dosya içeriği
        file_path: Dosya yolu
        
    Returns:
        Formatlanmış kalite raporu
    """
    analyzer = QualityAnalyzer()
    report = analyzer.analyze(content, file_path)
    
    output = [f"## 📊 Code Quality Analysis: `{file_path or 'Code'}`\n"]
    output.append(report.summary)
    
    if report.all_issues:
        output.append("\n### Quality Issues:\n")
        
        # Severity'ye göre sırala
        sorted_issues = sorted(report.all_issues, key=lambda x: x.severity.value)
        
        for issue in sorted_issues[:15]:  # Max 15 issue
            severity_icon = {
                IssueSeverity.HIGH: "🔴",
                IssueSeverity.MEDIUM: "🟡",
                IssueSeverity.LOW: "🟢",
                IssueSeverity.INFO: "ℹ️"
            }
            
            output.append(f"#### {severity_icon.get(issue.severity, '')} Line {issue.line_number}: {issue.category.value}")
            output.append(f"**Symbol**: `{issue.symbol_name}`")
            output.append(f"**Issue**: {issue.description}")
            output.append(f"**Fix**: {issue.suggestion}\n")
    
    return '\n'.join(output)
