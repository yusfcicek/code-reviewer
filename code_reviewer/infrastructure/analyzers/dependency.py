"""Finding the code a change reaches without touching.

The most expensive review misses are the ones outside the diff: a struct gains
a field, and three callers in two other modules now read garbage. Nothing in
the diff says so. This tracker searches the repository for the symbols a change
touched and reports where else they are used, one hop and two.
"""

import ast
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import ClassVar

from code_reviewer.domain.finding import AffectedCode, DependencyType
from code_reviewer.infrastructure.observability.logging import get_logger
from code_reviewer.infrastructure.tools.safe_search import (
    InvalidPatternError,
    build_grep_command,
)

logger = get_logger(__name__)


@dataclass
class ImpactReport:
    """Everything one symbol's change reaches."""

    source_symbol: str
    source_file: str
    affected_codes: list[AffectedCode] = field(default_factory=list)
    total_affected_files: int = 0
    risk_level: str = "low"  # low, medium, high, critical
    summary: str = ""


@dataclass
class CallGraphNode:
    """One function in a call graph, with its callers and callees."""

    name: str
    file_path: str
    line_number: int
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)


class DependencyTracker:
    """
    Finds the code that depends on a symbol that changed.

    The point is reach beyond the diff: when a data structure changes, its
    users are what breaks, and they are usually in files the merge request
    never opens.
    """

    # Extensions worth searching
    SUPPORTED_EXTENSIONS: ClassVar[set[str]] = {
        ".py",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".c",
        ".js",
        ".ts",
    }

    # Directories that are never worth searching
    EXCLUDED_DIRS: ClassVar[set[str]] = {
        "build",
        ".git",
        "__pycache__",
        "node_modules",
        ".gradle",
        ".idea",
        "venv",
        "env",
        ".venv",
    }

    def __init__(self, root_path: str = "."):
        self.root_path = os.path.abspath(root_path)
        self._symbol_cache: dict[str, list[str]] = {}
        self._file_cache: dict[str, str] = {}

    def track_data_structure_impact(self, struct_name: str) -> ImpactReport:
        """
        Reports everywhere a data structure is used.

        Args:
            struct_name: The struct, class or type whose shape changed.

        Returns:
            ImpactReport: every usage found, with a risk level derived from how
            many files are involved.
        """
        report = ImpactReport(source_symbol=struct_name, source_file="")

        # Every usage, anywhere in the tree
        affected = self._find_all_usages(struct_name)
        report.affected_codes = affected
        report.total_affected_files = len({a.file_path for a in affected})

        # Reach is the risk: the more files, the harder this is to verify
        if report.total_affected_files > 10:
            report.risk_level = "critical"
        elif report.total_affected_files > 5:
            report.risk_level = "high"
        elif report.total_affected_files > 2:
            report.risk_level = "medium"
        else:
            report.risk_level = "low"

        # ...summarised for the report
        report.summary = self._generate_impact_summary(report)

        return report

    def find_ripple_effects(self, changed_symbol: str, file_path: str | None = None) -> list[AffectedCode]:
        """
        Traces a change two hops out.

        Direct users first, then the users of those — which is where a change
        stops being obvious and starts being a surprise in production.
        """
        affected = []
        level_1 = self._find_all_usages(changed_symbol)

        for code in level_1:
            code.reason = f"Directly uses '{changed_symbol}'"
            affected.append(code)

            # 2. seviye: Bu kodu kullananlar
            if code.symbol_name:
                level_2 = self._find_all_usages(code.symbol_name)
                for l2_code in level_2[:5]:  # bounded: reach grows fast
                    l2_code.reason = f"Indirectly affected via '{code.symbol_name}'"
                    affected.append(l2_code)

        return affected

    def build_call_graph(self, entry_point: str, file_path: str) -> dict[str, CallGraphNode]:
        """
        Builds a call graph outwards from one function.

        Args:
            entry_point: The function to start from.
            file_path: Where it is defined.

        Returns:
            Function name to :class:`CallGraphNode`, three levels deep.
        """
        graph: dict[str, CallGraphNode] = {}
        visited: set[str] = set()

        self._build_graph_recursive(entry_point, file_path, graph, visited, depth=0, max_depth=3)

        return graph

    def get_affected_by_struct_change(self, struct_name: str) -> str:
        """
        Renders the impact analysis as markdown, for the agent's tool call.

        Returns:
            The report as markdown.
        """
        report = self.track_data_structure_impact(struct_name)

        output = [f"## Impact Analysis: `{struct_name}`\n"]
        output.append(f"**Risk Level**: {report.risk_level.upper()}")
        output.append(f"**Affected Files**: {report.total_affected_files}\n")

        if report.affected_codes:
            output.append("### Affected Code Locations:\n")

            # Group by file: a reviewer opens files, not line numbers
            by_file: dict[str, list[AffectedCode]] = {}
            for code in report.affected_codes:
                if code.file_path not in by_file:
                    by_file[code.file_path] = []
                by_file[code.file_path].append(code)

            for fp, codes in list(by_file.items())[:10]:  # first ten files
                output.append(f"\n**{fp}**:")
                for code in codes[:5]:  # at most five usages per file
                    output.append(
                        f"  - Line {code.line_number}: "
                        f"`{code.symbol_name or 'usage'}` "
                        f"({code.dependency_type.value if code.dependency_type else 'unknown'})"
                    )
                    if code.context:
                        output.append(f"    ```{code.context[:100]}...```")
        else:
            output.append("No usages found.")

        output.append(f"\n{report.summary}")

        return "\n".join(output)

    def _find_all_usages(self, symbol_name: str) -> list[AffectedCode]:
        """Finds usages with grep, which is fast enough across a repository."""
        affected = []

        # Built through the shared helper rather than by hand. This call site
        # was missed when G-06 fixed the one in the tool module: it had no
        # `--`, so a symbol starting with a dash was read as a flag; no `-F`,
        # so the symbol was a regular expression; and no exclusion of
        # credential files, so a matching line from `.env` came back. The
        # symbol reaches here from the model, which got it from the diff.
        try:
            cmd = build_grep_command(symbol_name, [self.root_path])
        except InvalidPatternError as exc:
            logger.debug(
                "Refused a usage search",
                extra={"fields": {"symbol": symbol_name, "reason": str(exc)}},
            )
            return []

        try:
            # `cmd` is built by build_grep_command, which validates the
            # pattern and places it after `--`.
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout:
                for line in result.stdout.strip().split("\n")[:50]:  # at most 50 hits
                    match = re.match(r"^([^:]+):(\d+):(.*)$", line)
                    if match:
                        file_path = match.group(1)
                        line_no = int(match.group(2))
                        context = match.group(3).strip()

                        # How is the symbol used here?
                        dep_type = self._classify_usage(context, symbol_name)

                        # ...and which function is it used from?
                        containing_func = self._find_containing_function(file_path, line_no)

                        affected.append(
                            AffectedCode(
                                file_path=file_path,
                                symbol_name=containing_func,
                                line_number=line_no,
                                dependency_type=dep_type,
                                context=context,
                            )
                        )

        except subprocess.TimeoutExpired:
            logger.debug("Symbol search timed out", extra={"fields": {"symbol": symbol_name}})
        except Exception as exc:
            logger.debug("Symbol search failed", extra={"fields": {"error": str(exc)}})

        return affected

    def _classify_usage(self, context: str, symbol_name: str) -> DependencyType:
        """Classifies how one line uses a symbol.

        Ordered by specificity: ``class Child(Target)`` looks like both an
        inheritance and a call, and inheritance is the more specific reading.

        The previous version searched for ``import``/``from`` anywhere in the
        line, and an operator-precedence mistake wrapped the final ``elif`` in a
        conditional expression, so the branch behaved by accident (finding
        F-08).
        """
        symbol = re.escape(symbol_name)

        if re.match(r"\s*(?:import|from)\s", context):
            return DependencyType.IMPORT

        if re.search(rf"class\s+\w+\s*\([^)]*\b{symbol}\b", context):
            return DependencyType.INHERITANCE

        if re.search(rf"\b{symbol}\s*\(", context):
            return DependencyType.DIRECT_CALL

        # Type annotation: `name: Target` in a variable, parameter or return.
        if re.search(rf":\s*[^=]*\b{symbol}\b", context) or re.search(rf"->\s*[^:]*\b{symbol}\b", context):
            return DependencyType.TYPE_USAGE

        return DependencyType.DATA_STRUCTURE

    def _find_containing_function(self, file_path: str, target_line: int) -> str:
        """The function a given line falls inside, if any."""
        try:
            if file_path.endswith(".py"):
                content = self._read_file_cached(file_path)
                if content:
                    return self._find_python_function(content, target_line)
        except (OSError, SyntaxError, ValueError) as exc:
            # An unreadable or unparseable file means "no containing function",
            # not a failed review — but the reason is recorded rather than
            # discarded, which is what the empty-handler rule is about.
            logger.debug("Cannot locate the containing function", extra={"fields": {"error": str(exc)}})

        return ""

    def _find_python_function(self, content: str, target_line: int) -> str:
        """The function a line falls inside, from a parsed module."""
        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                        if node.lineno <= target_line <= (node.end_lineno or node.lineno + 100):
                            return node.name

        except SyntaxError as exc:
            # Half-finished code on a branch is normal; report nothing, but
            # record why nothing was reported.
            logger.debug("Unparseable source; no symbols read", extra={"fields": {"error": str(exc)}})

        return ""

    def _read_file_cached(self, file_path: str) -> str | None:
        """Reads a file once and remembers it for the rest of the run."""
        if file_path in self._file_cache:
            return self._file_cache[file_path]

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
                self._file_cache[file_path] = content
                return content
        except OSError:
            return None

    def _build_graph_recursive(
        self,
        func_name: str,
        file_path: str,
        graph: dict[str, CallGraphNode],
        visited: set[str],
        depth: int,
        max_depth: int,
    ):
        """Walks outwards from one function, bounded by depth."""
        if depth >= max_depth or func_name in visited:
            return

        visited.add(func_name)

        # What this function calls
        callees = self._find_callees(func_name, file_path)

        # ...and what calls it
        callers = [
            a.symbol_name
            for a in self._find_all_usages(func_name)
            if a.symbol_name and a.dependency_type == DependencyType.DIRECT_CALL
        ]

        graph[func_name] = CallGraphNode(
            name=func_name,
            file_path=file_path,
            line_number=0,
            callers=callers[:10],
            callees=callees[:10],
        )

        # Then the same, one level further out
        for callee in callees[:5]:
            self._build_graph_recursive(callee, file_path, graph, visited, depth + 1, max_depth)

    def _find_callees(self, func_name: str, file_path: str) -> list[str]:
        """The functions one function calls, from its AST."""
        callees: list[str] = []

        content = self._read_file_cached(file_path)
        if not content or not file_path.endswith(".py"):
            return callees

        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == func_name:
                        # Every call inside this function
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call):
                                if isinstance(child.func, ast.Name):
                                    callees.append(child.func.id)
                                elif isinstance(child.func, ast.Attribute):
                                    callees.append(child.func.attr)
                        break

        except SyntaxError as exc:
            logger.debug("Unparseable source; no callees read", extra={"fields": {"error": str(exc)}})

        return list(set(callees))

    def _generate_impact_summary(self, report: ImpactReport) -> str:
        """A short summary of the impact, for the report header."""
        parts = []

        parts.append(f"### Impact Summary for `{report.source_symbol}`")

        if report.risk_level == "critical":
            parts.append("⚠️ **CRITICAL**: This change affects many parts of the codebase!")
        elif report.risk_level == "high":
            parts.append("⚠️ **HIGH RISK**: Significant impact expected.")

        parts.append(f"\n- **Total affected files**: {report.total_affected_files}")
        parts.append(f"- **Total affected locations**: {len(report.affected_codes)}")

        # Breakdown by how the symbol is used
        type_counts: dict[DependencyType, int] = {}
        for code in report.affected_codes:
            if code.dependency_type is None:
                continue
            type_counts[code.dependency_type] = type_counts.get(code.dependency_type, 0) + 1

        if type_counts:
            parts.append("\n**Usage breakdown**:")
            for dep_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                parts.append(f"  - {dep_type.value}: {count}")

        return "\n".join(parts)


def find_affected_by_struct(struct_name: str, root_path: str = ".") -> str:
    """
    Reports everywhere a data structure is used, for the agent's tool call.

    Args:
        struct_name: The struct or class whose shape changed.
        root_path: Where to search; the workspace root in a real run.

    Returns:
        The analysis as markdown.
    """
    tracker = DependencyTracker(root_path)
    return tracker.get_affected_by_struct_change(struct_name)


def find_ripple_effects(symbol_name: str, root_path: str = ".") -> str:
    """
    Traces a change two hops out, for the agent's tool call.
    """
    tracker = DependencyTracker(root_path)
    affected = tracker.find_ripple_effects(symbol_name)

    output = [f"## Ripple Effect Analysis: `{symbol_name}`\n"]
    output.append(f"**Total affected locations**: {len(affected)}\n")

    if affected:
        for code in affected[:20]:
            output.append(f"- **{code.file_path}:{code.line_number}**")
            output.append(f"  - Symbol: `{code.symbol_name or 'N/A'}`")
            output.append(f"  - Reason: {code.reason}")

    return "\n".join(output)
