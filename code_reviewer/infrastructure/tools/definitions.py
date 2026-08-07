"""Tools the review agent can call.

Every tool that touches disk goes through a :class:`Workspace`, which resolves
the path and refuses anything outside the repository under review. The paths
these tools receive are produced by the model, and the model's input includes
the diff — so an attacker who can open a merge request can attempt to steer them
(finding F-21). On a CI runner, an unconfined read reaches deploy keys,
environment files and other projects' checkouts, and the result is echoed into a
merge-request comment anyone can read.

Refusals come back as text the model can act on rather than as exceptions: the
review continues, with the model told why it cannot have the file.
"""

import ast
import re
import subprocess
from typing import List, Optional

from langchain.tools import StructuredTool

from .workspace import OutsideWorkspaceError, Workspace

#: Longest tool output handed back to the model. Beyond this the observation
#: crowds out the diff it is supposed to explain.
MAX_OUTPUT_CHARS = 2000

#: Directories never worth searching.
EXCLUDED_DIRS = ("build", ".git", "__pycache__", "node_modules", ".gradle", ".idea", ".venv")

_workspace: Optional[Workspace] = None


def set_workspace(workspace: Optional[Workspace]) -> None:
    """Sets the workspace every tool is confined to.

    Called once by the composition root. ``None`` restores the default, which
    is the current working directory.
    """
    global _workspace
    _workspace = workspace


def get_workspace() -> Workspace:
    """The active workspace, defaulting to the working directory."""
    global _workspace
    if _workspace is None:
        _workspace = Workspace()
    return _workspace


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n[... truncated at {MAX_OUTPUT_CHARS} characters ...]"


class FileSystemTools:

    @staticmethod
    def read_file(file_path: str) -> str:
        """Reads a file from inside the workspace."""
        try:
            return _truncate(get_workspace().read(file_path))
        except OutsideWorkspaceError as exc:
            return f"Refused: {exc}"
        except FileNotFoundError:
            return f"Error: File {file_path} not found."
        except Exception as exc:
            return f"Error reading file: {exc}"

    @staticmethod
    def list_files(path: str = ".") -> str:
        """Lists files in a directory inside the workspace."""
        workspace = get_workspace()
        try:
            target = workspace.resolve(path)
        except OutsideWorkspaceError as exc:
            return f"Refused: {exc}"

        if not target.is_dir():
            return f"Error: {path} is not a directory."

        entries = []
        for item in sorted(target.rglob("*")):
            if any(part in EXCLUDED_DIRS for part in item.parts):
                continue
            entries.append(workspace.relative(item))

        if not entries:
            return f"No files under {path}."
        return _truncate("\n".join(entries))


class CodeSearchTools:

    @staticmethod
    def grep_search(pattern: str, path: str = ".") -> str:
        """Searches for a text pattern inside the workspace."""
        workspace = get_workspace()
        try:
            root = workspace.resolve(path)
        except OutsideWorkspaceError as exc:
            return f"Refused: {exc}"

        command = ["grep", "-rnI"]
        command += [f"--exclude-dir={name}" for name in EXCLUDED_DIRS]
        # `--` and a literal pattern: the pattern comes from the model, and
        # shell=False means it is an argument rather than a command fragment.
        command += ["--", pattern, str(root)]

        try:
            output = subprocess.check_output(command, stderr=subprocess.DEVNULL).decode("utf-8")
        except subprocess.CalledProcessError:
            return "No matches found."
        except Exception as exc:
            return f"Error searching: {exc}"

        return _truncate(output)


class SmartFileTools:

    @staticmethod
    def find_file(filename: str) -> str:
        """Locates a file by name inside the workspace."""
        workspace = get_workspace()

        # Tolerate the model passing "name, path"; only the name is used.
        if "," in filename:
            filename = filename.split(",")[0].strip()

        matches = []
        for candidate in sorted(workspace.root.rglob(f"*{filename}*")):
            if any(part in EXCLUDED_DIRS for part in candidate.parts):
                continue
            if candidate.is_file():
                matches.append(workspace.relative(candidate))

        if not matches:
            return f"No file found matching '{filename}' in the workspace."
        if len(matches) > 5:
            return "Found multiple matches:\n" + "\n".join(matches[:5]) + "\n..."
        return "Found matches:\n" + "\n".join(matches)

    @staticmethod
    def read_symbol_definition(query: str) -> str:
        """Reads a symbol's definition.

        Input format: ``SymbolName in path/to/file.py``
        """
        if " in " not in query:
            return "Error: Input must be 'SymbolName in FilePath'."

        symbol, file_path = query.split(" in ", 1)
        symbol = symbol.strip("'\" ")
        file_path = file_path.strip("'\" ")

        try:
            content = get_workspace().read(file_path)
        except OutsideWorkspaceError as exc:
            return f"Refused: {exc}"
        except FileNotFoundError:
            return f"Error: File {file_path} not found."
        except Exception as exc:
            return f"Error reading symbol: {exc}"

        lines = content.splitlines()
        for index, line in enumerate(lines):
            if symbol in line:
                start = max(0, index - 5)
                end = min(len(lines), index + 50)
                excerpt = "\n".join(lines[start:end])
                return f"### Definition of `{symbol}` in `{file_path}`:\n```\n{excerpt}\n```"

        return f"Symbol '{symbol}' not found in {file_path}."


class DependencyAnalysisTools:

    @staticmethod
    def get_file_imports(file_path: str) -> str:
        """Lists imported modules. Supports Python (AST) and C/C++ (regex)."""
        try:
            content = get_workspace().read(file_path)
        except OutsideWorkspaceError as exc:
            return f"Refused: {exc}"
        except FileNotFoundError:
            return f"Error: File {file_path} not found."
        except Exception as exc:
            return f"Error analyzing imports: {exc}"

        if file_path.endswith((".cpp", ".cc", ".h", ".hpp", ".c")):
            includes = re.findall(r'#include\s+[<"](.+?)[>"]', content)
            if not includes:
                return "No includes found."
            return "Includes found:\n" + "\n".join(f"#include {name}" for name in includes)

        if file_path.endswith(".py"):
            try:
                tree = ast.parse(content, filename=file_path)
            except SyntaxError as exc:
                return f"Error analyzing imports: {exc}"

            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(f"import {alias.name}" for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    imports.extend(f"from {module} import {alias.name}" for alias in node.names)

            if not imports:
                return "No imports found."
            return "Imports found:\n" + "\n".join(imports)

        return "File type not supported for static dependency analysis."

    @staticmethod
    def find_references(symbol_name: str, root_path: str = ".") -> str:
        """Finds usages of a symbol inside the workspace."""
        if "," in symbol_name:
            symbol_name, root_path = (part.strip() for part in symbol_name.split(",", 1))

        result = CodeSearchTools.grep_search(symbol_name, root_path)
        if result == "No matches found.":
            return f"No references found for '{symbol_name}'."
        if result.startswith("Refused:"):
            return result
        return "References found:\n" + result


class AnalyzerTools:
    """Static analysis exposed as tools the model can call on demand.

    The same analyzers run unconditionally in the workflow, so a review is
    never left without them; these tools let the model look at a *different*
    file than the one under review.
    """

    @staticmethod
    def run_semantic_analysis(query: str) -> str:
        """Analyses a change semantically.

        Input format: ``diff ||| full_content ||| file_path``
        """
        try:
            from code_reviewer.infrastructure.analyzers.semantic import analyze_semantic_changes

            parts = query.split("|||")
            diff = parts[0].strip() if parts else ""
            full_content = parts[1].strip() if len(parts) > 1 else None
            file_path = parts[2].strip() if len(parts) > 2 else ""

            return analyze_semantic_changes(diff, full_content, file_path)
        except Exception as exc:
            return f"Error in semantic analysis: {exc}"

    @staticmethod
    def _read_for_analysis(file_path: str):
        """Returns (content, error_message); exactly one is not None."""
        try:
            return get_workspace().read(file_path), None
        except OutsideWorkspaceError as exc:
            return None, f"Refused: {exc}"
        except FileNotFoundError:
            return None, f"Error: File {file_path} not found."
        except Exception as exc:
            return None, f"Error reading {file_path}: {exc}"

    @staticmethod
    def run_sast_scan(file_path: str) -> str:
        """Runs the SAST security scan on a file."""
        content, error = AnalyzerTools._read_for_analysis(file_path)
        if error:
            return error
        from code_reviewer.infrastructure.analyzers.sast import run_sast_scan

        return run_sast_scan(content, file_path)

    @staticmethod
    def check_code_quality(file_path: str) -> str:
        """Checks SOLID principles, duplication, testability and error handling."""
        content, error = AnalyzerTools._read_for_analysis(file_path)
        if error:
            return error
        from code_reviewer.infrastructure.analyzers.quality import check_code_quality

        return check_code_quality(content, file_path)

    @staticmethod
    def analyze_performance(file_path: str) -> str:
        """Analyses complexity, resource leaks and N+1 patterns."""
        content, error = AnalyzerTools._read_for_analysis(file_path)
        if error:
            return error
        from code_reviewer.infrastructure.analyzers.performance import analyze_performance

        return analyze_performance(content, file_path)

    @staticmethod
    def find_affected_by_change(symbol_name: str) -> str:
        """Finds code affected by a change, including code outside the diff."""
        try:
            from code_reviewer.infrastructure.analyzers.dependency import find_affected_by_struct

            return find_affected_by_struct(symbol_name, str(get_workspace().root))
        except Exception as exc:
            return f"Error finding affected code: {exc}"

    @staticmethod
    def find_ripple_effects(symbol_name: str) -> str:
        """Traces a change's ripple effect two levels deep."""
        try:
            from code_reviewer.infrastructure.analyzers.dependency import find_ripple_effects

            return find_ripple_effects(symbol_name, str(get_workspace().root))
        except Exception as exc:
            return f"Error finding ripple effects: {exc}"


def get_tools() -> List[StructuredTool]:
    """Every tool the agent may call."""
    return [
        StructuredTool.from_function(
            func=FileSystemTools.read_file,
            name="read_file",
            description="Reads a file from the repository under review. Input: file_path (string).",
        ),
        StructuredTool.from_function(
            func=FileSystemTools.list_files,
            name="list_files",
            description="Lists files under a directory of the repository. Input: directory_path (string), defaults to '.'.",
        ),
        StructuredTool.from_function(
            func=CodeSearchTools.grep_search,
            name="grep_search",
            description="Searches the repository for a text pattern. Input: pattern (string).",
        ),
        StructuredTool.from_function(
            func=SmartFileTools.find_file,
            name="find_file",
            description="Locates a file by name in the repository. Input: filename (string).",
        ),
        StructuredTool.from_function(
            func=SmartFileTools.read_symbol_definition,
            name="read_symbol_definition",
            description="Reads one symbol's definition. Input: 'SymbolName in FilePath'. Example: 'handle in src/app.py'.",
        ),
        StructuredTool.from_function(
            func=DependencyAnalysisTools.get_file_imports,
            name="get_file_imports",
            description="Lists the modules a file imports. Input: file_path (string).",
        ),
        StructuredTool.from_function(
            func=DependencyAnalysisTools.find_references,
            name="find_references",
            description="Finds references to a symbol, to identify reverse dependencies. Input: symbol_name (string).",
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.run_sast_scan,
            name="run_sast_scan",
            description="Runs a SAST security scan: SQL injection, XSS, hardcoded secrets and more. Input: file_path (string).",
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.check_code_quality,
            name="check_code_quality",
            description="Checks SOLID principles, duplicate code, testability and error handling. Input: file_path (string).",
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.analyze_performance,
            name="analyze_performance",
            description="Analyses O(n²) complexity, memory leaks and N+1 query patterns. Input: file_path (string).",
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.find_affected_by_change,
            name="find_affected_by_change",
            description="Finds all code affected by a change, including code not in the diff. Input: symbol_name (string).",
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.run_semantic_analysis,
            name="run_semantic_analysis",
            description="Classifies a change as REFACTOR/FEATURE/BUGFIX/BREAKING_CHANGE. Input: 'diff ||| full_content ||| file_path'.",
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.find_ripple_effects,
            name="find_ripple_effects",
            description="Traces a change's ripple effect two levels deep. Input: symbol_name (string).",
        ),
    ]
