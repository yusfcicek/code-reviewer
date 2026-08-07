"""
Semantic Change Analyzer - AST tabanlı değişiklik analizi.

Bu modül Git diff'lerini semantik birimlere ayrıştırır ve değişiklik tipini tespit eder.
"""

import ast
import re
from dataclasses import dataclass, field
from enum import Enum


class ChangeType(Enum):
    """Değişiklik tipi kategorileri."""

    REFACTOR = "refactor"  # Davranış değişmeden yapısal değişiklik
    FEATURE = "feature"  # Yeni fonksiyonellik
    BUGFIX = "bugfix"  # Hata düzeltmesi
    BREAKING_CHANGE = "breaking"  # API/interface değişikliği
    DOCUMENTATION = "docs"  # Sadece yorum/docstring
    STYLE = "style"  # Whitespace, formatting
    UNKNOWN = "unknown"


class SymbolType(Enum):
    """Kod sembolü tipleri."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    VARIABLE = "variable"
    CONSTANT = "constant"
    STRUCT = "struct"
    IMPORT = "import"
    DATA_STRUCTURE = "data_structure"


@dataclass
class ChangedSymbol:
    """Değişen bir kod sembolünü temsil eder."""

    name: str
    symbol_type: SymbolType
    old_signature: str | None = None
    new_signature: str | None = None
    line_start: int = 0
    line_end: int = 0
    is_public: bool = True
    change_description: str = ""


@dataclass
class BreakingChange:
    """Breaking change detayları."""

    symbol: ChangedSymbol
    reason: str
    impact_level: str  # "high", "medium", "low"
    affected_callers: list[str] = field(default_factory=list)


@dataclass
class IntegrityIssue:
    """Kod bütünlüğü sorunu."""

    issue_type: str  # "incomplete_refactor", "missing_update", "orphaned_code"
    description: str
    affected_symbols: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class SemanticAnalysis:
    """Semantik analiz sonucu."""

    file_path: str
    change_type: ChangeType
    changed_symbols: list[ChangedSymbol] = field(default_factory=list)
    breaking_changes: list[BreakingChange] = field(default_factory=list)
    integrity_issues: list[IntegrityIssue] = field(default_factory=list)
    summary: str = ""
    risk_score: int = 0  # 0-100


class SemanticChangeAnalyzer:
    """
    Git diff'lerini semantik birimlere ayrıştırır ve analiz eder.

    Özellikler:
    - Değişen fonksiyonlar, sınıflar, veri yapıları tespit edilir
    - Değişiklik tipi: REFACTOR, FEATURE, BUGFIX, BREAKING_CHANGE
    - Bütünlük kontrolü: Eksik değişiklikler varsa uyarı
    """

    # Bir değişikliğin hata düzeltmesi olduğunu gösteren kelimeler. Kelime
    # sınırlarıyla yazılır: `prefix` bir `fix` değildir (F-13).
    BUGFIX_MARKERS = [
        r"\bfix(es|ed|ing)?\b",
        r"\bhotfix\b",
        r"\bbug\b",
        r"\bregression\b",
        r"\bworkaround\b",
        r"\bhata\b",
        r"\bdüzelt(me|ildi)?\b",
    ]

    # Public API işaretleyicileri
    PYTHON_PUBLIC_INDICATORS = {"def ", "class ", "async def "}
    CPP_PUBLIC_INDICATORS = {"public:", "struct ", "class ", "extern "}

    # Breaking change pattern'leri
    BREAKING_PATTERNS = {
        "python": [
            r"def\s+(\w+)\s*\([^)]*\)",  # Fonksiyon imzası
            r"class\s+(\w+)",  # Sınıf tanımı
            r"(\w+)\s*:\s*\w+",  # Type annotation değişikliği
        ],
        "cpp": [
            r"(?:struct|class)\s+(\w+)",  # Struct/class tanımı
            r"(?:void|int|bool|auto)\s+(\w+)\s*\([^)]*\)",  # Fonksiyon
            r"#define\s+(\w+)",  # Macro
        ],
    }

    def __init__(self):
        self._cached_asts: dict[str, ast.AST] = {}

    def analyze_diff(
        self, diff: str, full_content: str = None, file_path: str = ""
    ) -> SemanticAnalysis:
        """
        Git diff'i analiz eder ve semantik analiz sonucu döner.

        Args:
            diff: Git diff içeriği
            full_content: Dosyanın tam içeriği (opsiyonel)
            file_path: Dosya yolu

        Returns:
            SemanticAnalysis: Analiz sonucu
        """
        analysis = SemanticAnalysis(file_path=file_path, change_type=ChangeType.UNKNOWN)

        # Diff'i parçala
        added_lines, removed_lines, context_lines = self._parse_diff(diff)

        # Değişen sembolleri tespit et
        analysis.changed_symbols = self._extract_changed_symbols(
            added_lines, removed_lines, full_content, file_path
        )

        # Değişiklik tipini belirle
        analysis.change_type = self._classify_change_type(
            added_lines, removed_lines, analysis.changed_symbols
        )

        # Breaking change kontrolü
        analysis.breaking_changes = self._detect_breaking_changes(
            analysis.changed_symbols, removed_lines
        )

        # Bütünlük kontrolü
        if full_content:
            analysis.integrity_issues = self._check_integrity(
                analysis.changed_symbols, full_content
            )

        # Risk skoru hesapla
        analysis.risk_score = self._calculate_risk_score(analysis)

        # Özet oluştur
        analysis.summary = self._generate_summary(analysis)

        return analysis

    def _parse_diff(self, diff: str) -> tuple[list[str], list[str], list[str]]:
        """Diff'i eklenen, çıkarılan ve context satırlarına ayırır."""
        added = []
        removed = []
        context = []

        for line in diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:])
            elif not line.startswith("@@") and not line.startswith("diff "):
                context.append(line)

        return added, removed, context

    def _extract_changed_symbols(
        self, added_lines: list[str], removed_lines: list[str], full_content: str, file_path: str
    ) -> list[ChangedSymbol]:
        """Değişen sembolleri çıkarır."""
        symbols = []

        # Python dosyaları için AST kullan
        if file_path.endswith(".py") and full_content:
            try:
                tree = ast.parse(full_content)
                symbols.extend(self._extract_python_symbols(tree, added_lines, removed_lines))
            except SyntaxError:
                pass

        # Regex tabanlı genel analiz
        symbols.extend(self._extract_symbols_regex(added_lines, removed_lines, file_path))

        # Duplicate'leri kaldır
        seen = set()
        unique_symbols = []
        for sym in symbols:
            if sym.name not in seen:
                seen.add(sym.name)
                unique_symbols.append(sym)

        return unique_symbols

    def _extract_python_symbols(
        self, tree: ast.AST, added_lines: list[str], removed_lines: list[str]
    ) -> list[ChangedSymbol]:
        """Python AST'den değişen sembolleri çıkarır."""
        symbols = []
        all_changed_text = "\n".join(added_lines + removed_lines)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                if node.name in all_changed_text:
                    sig = self._get_function_signature(node)
                    symbols.append(
                        ChangedSymbol(
                            name=node.name,
                            symbol_type=SymbolType.FUNCTION,
                            new_signature=sig,
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                            is_public=not node.name.startswith("_"),
                        )
                    )

            elif isinstance(node, ast.ClassDef):
                if node.name in all_changed_text:
                    symbols.append(
                        ChangedSymbol(
                            name=node.name,
                            symbol_type=SymbolType.CLASS,
                            line_start=node.lineno,
                            line_end=node.end_lineno or node.lineno,
                            is_public=not node.name.startswith("_"),
                        )
                    )

        return symbols

    def _get_function_signature(self, node: ast.FunctionDef) -> str:
        """Fonksiyon imzasını string olarak döner."""
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            args.append(arg_str)

        return_annotation = ""
        if node.returns:
            return_annotation = f" -> {ast.unparse(node.returns)}"

        return f"def {node.name}({', '.join(args)}){return_annotation}"

    def _extract_symbols_regex(
        self, added_lines: list[str], removed_lines: list[str], file_path: str
    ) -> list[ChangedSymbol]:
        """Regex kullanarak sembolleri çıkarır (dil-agnostik)."""
        symbols = []
        all_lines = added_lines + removed_lines

        # Fonksiyon tanımları
        func_pattern = r"(?:def|void|int|bool|auto|function)\s+(\w+)\s*\("
        for line in all_lines:
            match = re.search(func_pattern, line)
            if match:
                symbols.append(
                    ChangedSymbol(
                        name=match.group(1),
                        symbol_type=SymbolType.FUNCTION,
                        is_public=not match.group(1).startswith("_"),
                    )
                )

        # Sınıf/struct tanımları
        class_pattern = r"(?:class|struct)\s+(\w+)"
        for line in all_lines:
            match = re.search(class_pattern, line)
            if match:
                symbols.append(
                    ChangedSymbol(
                        name=match.group(1),
                        symbol_type=SymbolType.CLASS if "class" in line else SymbolType.STRUCT,
                        is_public=True,
                    )
                )

        return symbols

    def _classify_change_type(
        self, added_lines: list[str], removed_lines: list[str], changed_symbols: list[ChangedSymbol]
    ) -> ChangeType:
        """Değişiklik tipini sınıflandırır."""
        added_text = "\n".join(added_lines).lower()
        removed_text = "\n".join(removed_lines).lower()

        # Hiç eklenen veya çıkarılan satır yoksa sınıflandıracak bir şey yok.
        # Bu kontrol olmadan `_is_only_style` iki boş listeyi karşılaştırıp
        # eşit buluyor ve değişiklik STYLE olarak etiketleniyordu (F-12).
        if not added_lines and not removed_lines:
            return ChangeType.UNKNOWN

        # Sadece yorum/docstring değişikliği
        if self._is_only_documentation(added_lines, removed_lines):
            return ChangeType.DOCUMENTATION

        # Sadece whitespace/formatting
        if self._is_only_style(added_lines, removed_lines):
            return ChangeType.STYLE

        # Bugfix işaretleri. Kelime sınırı olmadan `prefix`, `debug` ve
        # `error_handler` gibi sıradan tanımlayıcılar da eşleşiyordu (F-13).
        if any(
            re.search(pattern, added_text) or re.search(pattern, removed_text)
            for pattern in self.BUGFIX_MARKERS
        ):
            return ChangeType.BUGFIX

        # Breaking change: public API değişti
        public_changes = [s for s in changed_symbols if s.is_public]
        if public_changes and removed_lines:
            # İmza değişikliği var mı?
            for sym in public_changes:
                if sym.old_signature and sym.new_signature:
                    if sym.old_signature != sym.new_signature:
                        return ChangeType.BREAKING_CHANGE

        # Yeni fonksiyon/sınıf eklendi
        new_definitions = len(added_lines) > len(removed_lines) * 1.5
        if new_definitions and any(
            s.symbol_type in [SymbolType.FUNCTION, SymbolType.CLASS] for s in changed_symbols
        ):
            return ChangeType.FEATURE

        # Varsayılan: Refactor
        if removed_lines and added_lines:
            return ChangeType.REFACTOR

        return ChangeType.UNKNOWN

    def _is_only_documentation(self, added: list[str], removed: list[str]) -> bool:
        """Sadece dokümantasyon değişikliği mi kontrol eder."""
        doc_patterns = [r"^\s*#", r'^\s*"""', r"^\s*'''", r"^\s*//", r"^\s*/\*", r"^\s*\*"]

        for line in added + removed:
            is_doc = any(re.match(p, line) for p in doc_patterns) or not line.strip()
            if not is_doc:
                return False
        return True

    def _is_only_style(self, added: list[str], removed: list[str]) -> bool:
        """Sadece stil/formatting değişikliği mi kontrol eder."""
        # Whitespace'i kaldırarak karşılaştır
        added_normalized = [re.sub(r"\s+", "", line) for line in added]
        removed_normalized = [re.sub(r"\s+", "", line) for line in removed]

        return sorted(added_normalized) == sorted(removed_normalized)

    def _detect_breaking_changes(
        self, changed_symbols: list[ChangedSymbol], removed_lines: list[str]
    ) -> list[BreakingChange]:
        """Breaking change'leri tespit eder."""
        breaking_changes = []

        for symbol in changed_symbols:
            if not symbol.is_public:
                continue

            # Fonksiyon imzası değişti
            if symbol.old_signature and symbol.new_signature:
                if symbol.old_signature != symbol.new_signature:
                    breaking_changes.append(
                        BreakingChange(
                            symbol=symbol,
                            reason=f"Function signature changed from '{symbol.old_signature}' to '{symbol.new_signature}'",
                            impact_level="high",
                        )
                    )

            # Fonksiyon/sınıf kaldırıldı
            if symbol.symbol_type in [SymbolType.FUNCTION, SymbolType.CLASS]:
                for line in removed_lines:
                    if f"def {symbol.name}" in line or f"class {symbol.name}" in line:
                        breaking_changes.append(
                            BreakingChange(
                                symbol=symbol,
                                reason=f"Public {symbol.symbol_type.value} '{symbol.name}' was removed or renamed",
                                impact_level="high",
                            )
                        )
                        break

        return breaking_changes

    def _check_integrity(
        self, changed_symbols: list[ChangedSymbol], full_content: str
    ) -> list[IntegrityIssue]:
        """Kod bütünlüğünü kontrol eder."""
        issues = []

        # Değişen sembollerin referanslarını kontrol et
        for symbol in changed_symbols:
            # Kullanım sayısını bul
            usage_count = len(re.findall(rf"\b{symbol.name}\b", full_content))

            # Sembol tanımlanmış ama bu dosyada bir daha geçmiyorsa.
            #
            # Analiz yalnızca tek bir dosyayı görüyor, dolayısıyla başka bir
            # modülden çağrılıp çağrılmadığını bilemez. Eski metin bunu
            # "never called" diye kesin bir iddiaya çeviriyordu (F-14);
            # ripple analizi için `find_references` aracı kullanılmalıdır.
            if usage_count == 1 and symbol.symbol_type == SymbolType.FUNCTION:
                issues.append(
                    IntegrityIssue(
                        issue_type="unreferenced_in_file",
                        description=(
                            f"Function '{symbol.name}' is not referenced anywhere else in "
                            f"this file — callers, if any, live in other modules"
                        ),
                        affected_symbols=[symbol.name],
                        suggestion=(
                            "Run find_references to confirm whether callers exist elsewhere "
                            "before treating this as dead code"
                        ),
                    )
                )

        return issues

    def _calculate_risk_score(self, analysis: SemanticAnalysis) -> int:
        """Risk skoru hesaplar (0-100)."""
        score = 0

        # Change type bazlı skor
        type_scores = {
            ChangeType.DOCUMENTATION: 5,
            ChangeType.STYLE: 5,
            ChangeType.BUGFIX: 30,
            ChangeType.REFACTOR: 40,
            ChangeType.FEATURE: 50,
            ChangeType.BREAKING_CHANGE: 80,
            ChangeType.UNKNOWN: 60,
        }
        score += type_scores.get(analysis.change_type, 50)

        # Breaking change'ler için ek puan
        score += len(analysis.breaking_changes) * 10

        # Integrity issue'lar için ek puan
        score += len(analysis.integrity_issues) * 5

        # Public sembol değişiklikleri
        public_changes = sum(1 for s in analysis.changed_symbols if s.is_public)
        score += public_changes * 5

        return min(100, score)

    def _generate_summary(self, analysis: SemanticAnalysis) -> str:
        """Analiz özeti oluşturur."""
        parts = []

        parts.append(f"**Change Type**: {analysis.change_type.value.upper()}")
        parts.append(f"**Risk Score**: {analysis.risk_score}/100")

        if analysis.changed_symbols:
            symbol_names = [s.name for s in analysis.changed_symbols[:5]]
            parts.append(f"**Changed Symbols**: {', '.join(symbol_names)}")

        if analysis.breaking_changes:
            parts.append(f"⚠️ **Breaking Changes**: {len(analysis.breaking_changes)} detected")

        if analysis.integrity_issues:
            parts.append(f"🔍 **Integrity Issues**: {len(analysis.integrity_issues)} found")

        return "\n".join(parts)


def analyze_semantic_changes(diff: str, full_content: str = None, file_path: str = "") -> str:
    """
    Tool wrapper - Semantik değişiklik analizi yapar.

    Args:
        diff: Git diff içeriği
        full_content: Dosyanın tam içeriği
        file_path: Dosya yolu

    Returns:
        Analiz sonucu (string formatında)
    """
    analyzer = SemanticChangeAnalyzer()
    result = analyzer.analyze_diff(diff, full_content, file_path)

    output = [f"## Semantic Analysis: {file_path or 'Unknown File'}\n"]
    output.append(result.summary)

    if result.breaking_changes:
        output.append("\n### ⚠️ Breaking Changes:")
        for bc in result.breaking_changes:
            output.append(f"- **{bc.symbol.name}**: {bc.reason} (Impact: {bc.impact_level})")

    if result.integrity_issues:
        output.append("\n### 🔍 Integrity Issues:")
        for issue in result.integrity_issues:
            output.append(f"- **{issue.issue_type}**: {issue.description}")
            if issue.suggestion:
                output.append(f"  - Suggestion: {issue.suggestion}")

    if result.changed_symbols:
        output.append("\n### Changed Symbols:")
        for sym in result.changed_symbols[:10]:
            output.append(f"- `{sym.name}` ({sym.symbol_type.value})")

    return "\n".join(output)
