"""What a change *means*, rather than what it touches.

A diff shows lines. This analyzer parses it into symbols — functions, classes,
structs — and classifies the change: a refactor, a feature, a bug fix or a
break. That classification is what lets the review say "this removes a public
method" rather than "this deletes eight lines".
"""

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from code_reviewer.infrastructure.observability.logging import get_logger

logger = get_logger(__name__)


class ChangeType(Enum):
    """What kind of change a diff represents."""

    REFACTOR = "refactor"  # structure moved, behaviour unchanged
    FEATURE = "feature"  # Yeni fonksiyonellik
    BUGFIX = "bugfix"  # a defect corrected
    BREAKING_CHANGE = "breaking"  # callers must change too
    DOCUMENTATION = "docs"  # Sadece yorum/docstring
    STYLE = "style"  # Whitespace, formatting
    UNKNOWN = "unknown"


class SymbolType(Enum):
    """The kinds of symbol a change can touch."""

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
    """One symbol the change touched."""

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
    """A change that requires callers to be updated."""

    symbol: ChangedSymbol
    reason: str
    impact_level: str  # "high", "medium", "low"
    affected_callers: list[str] = field(default_factory=list)


@dataclass
class IntegrityIssue:
    """A sign the change may be incomplete."""

    issue_type: str  # "incomplete_refactor", "missing_update", "orphaned_code"
    description: str
    affected_symbols: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class SemanticAnalysis:
    """What the analyzer concluded about one diff."""

    file_path: str
    change_type: ChangeType
    changed_symbols: list[ChangedSymbol] = field(default_factory=list)
    breaking_changes: list[BreakingChange] = field(default_factory=list)
    integrity_issues: list[IntegrityIssue] = field(default_factory=list)
    summary: str = ""
    risk_score: int = 0  # 0-100


class SemanticChangeAnalyzer:
    """
    Parses a diff into symbols and classifies what happened to them.

    - identifies the functions, classes and data structures that moved
    - classifies the change as REFACTOR, FEATURE, BUGFIX or BREAKING_CHANGE
    - flags signs that the change is incomplete
    """

    # Words that mark a change as a bug fix, written with word boundaries:
    # `prefix` is not a `fix` (finding F-13).
    #
    # These are patterns matched against the code under review, not prose in
    # this project, so the list is deliberately multilingual: the reviewed
    # repository's comments may be in any language its team writes in. Turkish
    # is included because that is the first deployment target.
    BUGFIX_MARKERS: ClassVar[list[str]] = [
        r"\bfix(es|ed|ing)?\b",
        r"\bhotfix\b",
        r"\bbug\b",
        r"\bregression\b",
        r"\bworkaround\b",
        r"\bcorrect(s|ed|ion)?\b",
        # Turkish equivalents of defect and to-correct
        r"\bhata\b",
        r"\bd\u00fczelt(me|ildi)?\b",
    ]

    # Markers of a public declaration, per language
    PYTHON_PUBLIC_INDICATORS: ClassVar[set[str]] = {"def ", "class ", "async def "}
    CPP_PUBLIC_INDICATORS: ClassVar[set[str]] = {"public:", "struct ", "class ", "extern "}

    # Breaking change pattern'leri
    BREAKING_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "python": [
            r"def\s+(\w+)\s*\([^)]*\)",  # function signature
            r"class\s+(\w+)",  # class definition
            r"(\w+)\s*:\s*\w+",  # type annotation
        ],
        "cpp": [
            r"(?:struct|class)\s+(\w+)",  # struct or class definition
            r"(?:void|int|bool|auto)\s+(\w+)\s*\([^)]*\)",  # Fonksiyon
            r"#define\s+(\w+)",  # Macro
        ],
    }

    def __init__(self):
        self._cached_asts: dict[str, ast.AST] = {}

    def analyze_diff(
        self, diff: str, full_content: str | None = None, file_path: str = ""
    ) -> SemanticAnalysis:
        """
        Analyses one diff.

        Args:
            diff: The unified diff for this file.
            full_content: The file at the reviewed commit, when it could be read.
                Without it, the analysis falls back to regex over the diff.
            file_path: Used to pick the language.

        Returns:
            SemanticAnalysis: Analiz sonucu
        """
        analysis = SemanticAnalysis(file_path=file_path, change_type=ChangeType.UNKNOWN)

        # Split the diff into added, removed and context lines
        added_lines, removed_lines, _context_lines = self._parse_diff(diff)

        # Identify what the change touched
        analysis.changed_symbols = self._extract_changed_symbols(
            added_lines, removed_lines, full_content, file_path
        )

        # Classify it
        analysis.change_type = self._classify_change_type(
            added_lines, removed_lines, analysis.changed_symbols
        )

        # Look for changes that callers must follow
        analysis.breaking_changes = self._detect_breaking_changes(analysis.changed_symbols, removed_lines)

        # ...and for signs the change is only half done
        if full_content:
            analysis.integrity_issues = self._check_integrity(analysis.changed_symbols, full_content)

        # Reduce all of that to one number
        analysis.risk_score = self._calculate_risk_score(analysis)

        # ...and one paragraph
        analysis.summary = self._generate_summary(analysis)

        return analysis

    def _parse_diff(self, diff: str) -> tuple[list[str], list[str], list[str]]:
        """Splits a diff into its added, removed and unchanged lines."""
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
        """Collects the symbols the change touched, AST first, regex second."""
        symbols = []

        # An AST is precise; use it whenever the file parses
        if file_path.endswith(".py") and full_content:
            try:
                tree = ast.parse(full_content)
                symbols.extend(self._extract_python_symbols(tree, added_lines, removed_lines))
            except SyntaxError as exc:
                logger.debug("Unparseable source; no symbols read", extra={"fields": {"error": str(exc)}})

        # Regex catches other languages, and Python that no longer parses
        symbols.extend(self._extract_symbols_regex(added_lines, removed_lines, file_path))

        # One entry per symbol name
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
        """Collects touched symbols from a parsed Python module."""
        symbols = []
        all_changed_text = "\n".join(added_lines + removed_lines)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
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

            elif isinstance(node, ast.ClassDef) and node.name in all_changed_text:
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
        """Renders a function signature, for comparing before and after."""
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
        """Collects symbols by pattern, for languages without an AST here."""
        symbols = []
        all_lines = added_lines + removed_lines

        # Function definitions
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

        # Class and struct definitions
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
        """Classifies the change, most specific category first."""
        added_text = "\n".join(added_lines).lower()
        removed_text = "\n".join(removed_lines).lower()

        # Nothing added and nothing removed means nothing to classify.
        # Without this guard `_is_only_style` compared two empty lists, found
        # them equal, and labelled the change STYLE (finding F-12).
        if not added_lines and not removed_lines:
            return ChangeType.UNKNOWN

        # Comments and docstrings only
        if self._is_only_documentation(added_lines, removed_lines):
            return ChangeType.DOCUMENTATION

        # Whitespace and formatting only
        if self._is_only_style(added_lines, removed_lines):
            return ChangeType.STYLE

        if self._mentions_a_bugfix(added_text, removed_text):
            return ChangeType.BUGFIX

        if removed_lines and self._breaks_a_public_signature(changed_symbols):
            return ChangeType.BREAKING_CHANGE

        if self._adds_a_definition(added_lines, removed_lines, changed_symbols):
            return ChangeType.FEATURE

        # Something moved both ways without a clearer signal
        if removed_lines and added_lines:
            return ChangeType.REFACTOR

        return ChangeType.UNKNOWN

    def _mentions_a_bugfix(self, added_text: str, removed_text: str) -> bool:
        """Whether either side names a fix.

        Without word boundaries, ordinary identifiers such as `prefix`,
        `debug` and `error_handler` matched too (finding F-13).
        """
        return any(
            re.search(pattern, added_text) or re.search(pattern, removed_text)
            for pattern in self.BUGFIX_MARKERS
        )

    @staticmethod
    def _breaks_a_public_signature(changed_symbols: list[ChangedSymbol]) -> bool:
        """Whether a public signature changed — and was visible on both sides.

        A symbol whose old or new signature could not be read is not evidence
        of a break; it is evidence of a diff we could not fully parse.
        """
        return any(
            symbol.is_public
            and symbol.old_signature
            and symbol.new_signature
            and symbol.old_signature != symbol.new_signature
            for symbol in changed_symbols
        )

    @staticmethod
    def _adds_a_definition(
        added_lines: list[str], removed_lines: list[str], changed_symbols: list[ChangedSymbol]
    ) -> bool:
        """Mostly additions, and at least one of them defines something."""
        mostly_additions = len(added_lines) > len(removed_lines) * 1.5
        return mostly_additions and any(
            symbol.symbol_type in (SymbolType.FUNCTION, SymbolType.CLASS) for symbol in changed_symbols
        )

    def _is_only_documentation(self, added: list[str], removed: list[str]) -> bool:
        """True when every changed line is a comment, docstring or blank."""
        doc_patterns = [r"^\s*#", r'^\s*"""', r"^\s*'''", r"^\s*//", r"^\s*/\*", r"^\s*\*"]

        for line in added + removed:
            is_doc = any(re.match(p, line) for p in doc_patterns) or not line.strip()
            if not is_doc:
                return False
        return True

    def _is_only_style(self, added: list[str], removed: list[str]) -> bool:
        """True when the change only moves whitespace around."""
        # Compare with whitespace stripped and order ignored
        added_normalized = [re.sub(r"\s+", "", line) for line in added]
        removed_normalized = [re.sub(r"\s+", "", line) for line in removed]

        return sorted(added_normalized) == sorted(removed_normalized)

    def _detect_breaking_changes(
        self, changed_symbols: list[ChangedSymbol], removed_lines: list[str]
    ) -> list[BreakingChange]:
        """Finds the changes that require callers to be updated."""
        breaking_changes = []

        for symbol in changed_symbols:
            if not symbol.is_public:
                continue

            # The signature changed
            if symbol.old_signature and symbol.new_signature:
                if symbol.old_signature != symbol.new_signature:
                    breaking_changes.append(
                        BreakingChange(
                            symbol=symbol,
                            reason=(
                                f"Function signature changed from "
                                f"'{symbol.old_signature}' to '{symbol.new_signature}'"
                            ),
                            impact_level="high",
                        )
                    )

            # ...or the symbol went away entirely
            if symbol.symbol_type in [SymbolType.FUNCTION, SymbolType.CLASS]:
                for line in removed_lines:
                    if f"def {symbol.name}" in line or f"class {symbol.name}" in line:
                        breaking_changes.append(
                            BreakingChange(
                                symbol=symbol,
                                reason=(
                                    f"Public {symbol.symbol_type.value} "
                                    f"'{symbol.name}' was removed or renamed"
                                ),
                                impact_level="high",
                            )
                        )
                        break

        return breaking_changes

    def _check_integrity(
        self, changed_symbols: list[ChangedSymbol], full_content: str
    ) -> list[IntegrityIssue]:
        """Looks for signs the change was left half done."""
        issues = []

        # How often does each touched symbol appear in this file?
        for symbol in changed_symbols:
            # One occurrence means the definition and nothing else
            usage_count = len(re.findall(rf"\b{symbol.name}\b", full_content))

            # Defined here and referenced nowhere else in this file.
            #
            # The analyzer sees one file, so it cannot know whether another
            # module calls it. The wording used to claim "never called", which
            # is more than the evidence supports (finding F-14); confirming it
            # needs the `find_references` tool.
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

        # Base score from what kind of change this is
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

        # Each break adds to it
        score += len(analysis.breaking_changes) * 10

        # ...as does each sign of incompleteness
        score += len(analysis.integrity_issues) * 5

        # ...and each public symbol touched
        public_changes = sum(1 for s in analysis.changed_symbols if s.is_public)
        score += public_changes * 5

        return min(100, score)

    def _generate_summary(self, analysis: SemanticAnalysis) -> str:
        """A short summary of what the analysis concluded."""
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


def analyze_semantic_changes(diff: str, full_content: str | None = None, file_path: str = "") -> str:
    """
    Runs the analysis and renders it as markdown, for the agent's tool call.

    Args:
        diff: The unified diff for this file.
        full_content: The file at the reviewed commit, when it could be read.
        file_path: Used to pick the language.

    Returns:
        The analysis as markdown.
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
