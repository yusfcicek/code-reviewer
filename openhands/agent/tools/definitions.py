import os
import subprocess
from typing import List, Optional
from langchain.tools import StructuredTool

class FileSystemTools:
    
    @staticmethod
    def read_file(file_path: str) -> str:
        """Reads a file from the local filesystem."""
        try:
            if not os.path.exists(file_path):
                return f"Error: File {file_path} not found."
            with open(file_path, 'r') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    @staticmethod
    def list_files(path: str = ".") -> str:
        """Lists files in a directory."""
        try:
             # Basic implementation, could actully use `ls -R` or `find`
             return subprocess.check_output(["ls", "-R", path]).decode('utf-8')
        except Exception as e:
            return f"Error listing files: {e}"

class CodeSearchTools:
    
    @staticmethod
    def grep_search(pattern: str, path: str = ".") -> str:
        """Searches for a pattern using grep."""
        try:
            # Using basic grep
            result = subprocess.check_output(["grep", "-rn", pattern, path]).decode('utf-8')
            # Limit output length?
            return result[:2000] if len(result) > 2000 else result
        except subprocess.CalledProcessError:
            return "No matches found."
        except Exception as e:
            return f"Error searching: {e}"

class SmartFileTools:

    @staticmethod
    def find_file(filename: str) -> str:
        """
        Locates a file by name.
        Input: filename (string).
        """
        # Parse if multiple args were attempted (naive)
        path = "."
        if "," in filename:
             parts = filename.split(",")
             filename = parts[0].strip()
        
        try:
            # First, try exact match
            if os.path.exists(os.path.join(path, filename)):
                return os.path.join(path, filename)
            
            cmd = ["find", path, "-name", f"*{filename}*"]
            result = subprocess.check_output(cmd).decode('utf-8').strip()
            
            if not result:
                return f"No file found matching '{filename}' in '{path}'."
            
            matches = result.split('\n')
            if len(matches) > 5:
                return "Found multiple matches:\n" + "\n".join(matches[:5]) + "\n..."
            return "Found matches:\n" + "\n".join(matches)
            
        except Exception as e:
            return f"Error finding file: {e}"

    @staticmethod
    def read_symbol_definition(query: str) -> str:
        """
        Reads definition of a symbol.
        Input format: "symbol_name in file_path" 
        Example: "MyClass in src/utils.py"
        """
        try:
            if " in " not in query:
                return "Error: Input must be 'SymbolName in FilePath'."
                
            symbol, file_path = query.split(" in ", 1)
            symbol = symbol.strip("'\" ")
            file_path = file_path.strip("'\" ")

            if not os.path.exists(file_path):
                return f"Error: File {file_path} not found."
                
            cmd = ["grep", "-n", symbol, file_path]
            try:
                result = subprocess.check_output(cmd).decode('utf-8').strip()
            except subprocess.CalledProcessError:
                return f"Symbol '{symbol}' not found in '{file_path}' (grep failed)."

            if not result:
                return f"Symbol '{symbol}' not found in {file_path}."
                
            first_match = result.split('\n')[0]
            line_no_str = first_match.split(':')[0]
            
            if not line_no_str.isdigit():
                 return f"Could not parse line number."
            
            line_no = int(line_no_str)
            start_line = max(1, line_no - 5)
            end_line = line_no + 50 
            
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            selected_lines = lines[start_line-1:end_line]
            content = "".join(selected_lines)
            
            return f"### Definition of `{symbol}` in `{file_path}`:\n```\n{content}\n```"
            
        except Exception as e:
            return f"Error reading symbol: {e}"


class DependencyAnalysisTools:
    
    @staticmethod
    def get_file_imports(file_path: str) -> str:
        """
        Lists imported modules/files. Supports Python (AST) and C++ (Regex).
        Input: file_path (string).
        """
        import ast
        import re
        
        try:
            if not os.path.exists(file_path):
                return f"Error: File {file_path} not found."
            
            # C++ Support
            if file_path.endswith(('.cpp', '.cc', '.h', '.hpp')):
                with open(file_path, 'r') as f:
                    content = f.read()
                # Regex for #include "..." or #include <...>
                includes = re.findall(r'#include\s+[<"](.+?)[>"]', content)
                if not includes:
                    return "No includes found."
                return "Includes found:\n" + "\n".join(f"#include {i}" for i in includes)

            # Python Support
            if file_path.endswith('.py'):
                with open(file_path, 'r') as f:
                    tree = ast.parse(f.read(), filename=file_path)
                
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(f"import {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ''
                        for alias in node.names:
                            imports.append(f"from {module} import {alias.name}")
                
                if not imports:
                    return "No imports found."
                return "Imports found:\n" + "\n".join(imports)
                
            return "File type not supported for static dependency analysis."
            
        except Exception as e:
            return f"Error analyzing imports: {e}"

    @staticmethod
    def find_references(symbol_name: str, root_path: str = ".") -> str:
        """
        Scans files for usages of a symbol (class/function/file).
        Input: "SymbolName" or "SymbolName, path"
        """
        # Simple text search wrapper for wider compatibility
        # Replaces simple find_class_refs
        if "," in symbol_name:
            parts = symbol_name.split(",", 1)
            symbol_name = parts[0].strip()
            root_path = parts[1].strip()
            
        # Exclude common build/artifact directories and ignore binary files (-I)
        cmd = [
            "grep", "-rnI", 
            "--exclude-dir=build", 
            "--exclude-dir=.git", 
            "--exclude-dir=__pycache__", 
            "--exclude-dir=node_modules", 
            "--exclude-dir=.gradle", 
            "--exclude-dir=.idea",
            symbol_name, 
            root_path
        ]
        try:
            # stderr=subprocess.DEVNULL to hide specific warnings like "permission denied" or weird binary matches
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8')
            
            # Filter output size
            lines = output.split('\n')
            if len(lines) > 20:
                return f"Found {len(lines)} references. First 20:\n" + "\n".join(lines[:20])
            return "References found:\n" + output
        except subprocess.CalledProcessError:
            return f"No references found for '{symbol_name}'."
        except Exception as e:
            return f"Error searching references: {e}"


class AnalyzerTools:
    """Gelişmiş analiz araçları - semantik, güvenlik, kalite ve performans."""
    
    @staticmethod
    def run_semantic_analysis(query: str) -> str:
        """
        Semantik değişim analizi yapar.
        Input: 'diff_content' veya 'diff_content, file_content'
        """
        try:
            from openhands.agent.analyzers.semantic_analyzer import analyze_semantic_changes
            
            # Parse input
            parts = query.split('|||')  # Use ||| as separator
            diff = parts[0].strip() if parts else ""
            full_content = parts[1].strip() if len(parts) > 1 else None
            file_path = parts[2].strip() if len(parts) > 2 else ""
            
            return analyze_semantic_changes(diff, full_content, file_path)
        except ImportError as e:
            return f"Semantic analyzer not available: {e}"
        except Exception as e:
            return f"Error in semantic analysis: {e}"
    
    @staticmethod
    def run_sast_scan(file_path: str) -> str:
        """
        SAST güvenlik taraması yapar.
        Input: file_path (string)
        """
        try:
            from openhands.agent.analyzers.sast_analyzer import run_sast_scan
            
            # Read file content
            if not os.path.exists(file_path):
                return f"Error: File {file_path} not found."
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return run_sast_scan(content, file_path)
        except ImportError as e:
            return f"SAST analyzer not available: {e}"
        except Exception as e:
            return f"Error in SAST scan: {e}"
    
    @staticmethod
    def check_code_quality(file_path: str) -> str:
        """
        SOLID prensipleri ve kod kalitesi kontrolü yapar.
        Input: file_path (string)
        """
        try:
            from openhands.agent.analyzers.quality_analyzer import check_code_quality
            
            if not os.path.exists(file_path):
                return f"Error: File {file_path} not found."
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return check_code_quality(content, file_path)
        except ImportError as e:
            return f"Quality analyzer not available: {e}"
        except Exception as e:
            return f"Error in quality check: {e}"
    
    @staticmethod
    def analyze_performance(file_path: str) -> str:
        """
        Performans analizi yapar - O(n²), memory leak tespiti.
        Input: file_path (string)
        """
        try:
            from openhands.agent.analyzers.performance_analyzer import analyze_performance
            
            if not os.path.exists(file_path):
                return f"Error: File {file_path} not found."
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return analyze_performance(content, file_path)
        except ImportError as e:
            return f"Performance analyzer not available: {e}"
        except Exception as e:
            return f"Error in performance analysis: {e}"
    
    @staticmethod
    def find_affected_by_change(symbol_name: str) -> str:
        """
        Bir değişiklikten etkilenen tüm kodu bulur (git diff dışındakiler dahil).
        Input: symbol_name (string) - değişen struct/class/function adı
        """
        try:
            from openhands.agent.analyzers.dependency_tracker import find_affected_by_struct
            return find_affected_by_struct(symbol_name)
        except ImportError as e:
            return f"Dependency tracker not available: {e}"
        except Exception as e:
            return f"Error finding affected code: {e}"
            
    @staticmethod
    def find_ripple_effects(symbol_name: str) -> str:
        """
        Değişikliğin dalga etkisini hesaplar (2 seviye derinlikte).
        Input: symbol_name (string)
        """
        try:
            from openhands.agent.analyzers.dependency_tracker import find_ripple_effects
            return find_ripple_effects(symbol_name)
        except ImportError as e:
            return f"Dependency tracker not available: {e}"
        except Exception as e:
            return f"Error finding ripple effects: {e}"


def get_tools() -> List[StructuredTool]:
    """Tüm agent araçlarını döner."""
    tools = [
        # Dosya sistemi araçları
        StructuredTool.from_function(
            func=FileSystemTools.read_file,
            name="read_file",
            description="Reads the ENTIRE content of a file. Input: file_path (string)."
        ),
        StructuredTool.from_function(
            func=FileSystemTools.list_files,
            name="list_files",
            description="Lists files in a directory. Input: directory_path (string), defaults to '.' "
        ),
        
        # Kod arama araçları
        StructuredTool.from_function(
            func=CodeSearchTools.grep_search,
            name="grep_search",
            description="Searches for a text pattern. Input: pattern (string)."
        ),
        StructuredTool.from_function(
            func=SmartFileTools.find_file,
            name="find_file",
            description="Locates a file path. Input: filename (string)."
        ),
        StructuredTool.from_function(
            func=SmartFileTools.read_symbol_definition,
            name="read_symbol_definition",
            description="Reads ONLY a symbol definition. Input: 'SymbolName in FilePath' (string). Example: 'MyFunction in src/main.py'"
        ),
        
        # Bağımlılık analizi araçları
        StructuredTool.from_function(
            func=DependencyAnalysisTools.get_file_imports,
            name="get_file_imports",
            description="Returns a list of imported modules in a file. Input: file_path (string)."
        ),
        StructuredTool.from_function(
            func=DependencyAnalysisTools.find_references,
            name="find_references",
            description="Finds text references to a symbol (class/func) to identify dependencies. Input: symbol_name (string) OR 'symbol_name, root_path'."
        ),
        
        # YENİ: Gelişmiş analiz araçları
        StructuredTool.from_function(
            func=AnalyzerTools.run_sast_scan,
            name="run_sast_scan",
            description="Runs SAST security scan on a file. Detects SQL injection, XSS, hardcoded secrets, etc. Input: file_path (string)."
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.check_code_quality,
            name="check_code_quality",
            description="Checks SOLID principles, duplicate code, testability, error handling. Input: file_path (string)."
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.analyze_performance,
            name="analyze_performance",
            description="Analyzes performance issues: O(n²) complexity, memory leaks, N+1 patterns. Input: file_path (string)."
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.find_affected_by_change,
            name="find_affected_by_change",
            description="Finds ALL code affected by a change, including code NOT in git diff. Critical for data structure changes. Input: symbol_name (string)."
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.run_semantic_analysis,
            name="run_semantic_analysis",
            description="Analyzes semantic changes (REFACTOR/FEATURE/BUGFIX), checks completeness and breaking changes. Input: 'diff ||| full_content ||| file_path'"
        ),
        StructuredTool.from_function(
            func=AnalyzerTools.find_ripple_effects,
            name="find_ripple_effects",
            description="Analyzes the ripple effect of a change (2 levels deep). Use for high-risk refactors. Input: symbol_name (string)."
        ),
    ]
    
    return tools

