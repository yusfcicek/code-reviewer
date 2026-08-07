"""
Dependency Tracker - Bağımlılık analizi ve etki takibi.

Git diff'te görünmeyen ama değişikliklerden etkilenen kodları tespit eder.
Özellikle veri yapıları değiştiğinde tüm kullanıcıları bulur.
"""

import ast
import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Tuple


class DependencyType(Enum):
    """Bağımlılık tipi."""
    DIRECT_CALL = "direct_call"           # Fonksiyon çağrısı
    INHERITANCE = "inheritance"            # Sınıf kalıtımı
    COMPOSITION = "composition"            # Sınıf içinde kullanım
    IMPORT = "import"                      # Import ifadesi
    TYPE_USAGE = "type_usage"              # Type annotation
    DATA_STRUCTURE = "data_structure"      # Veri yapısı kullanımı


@dataclass
class AffectedCode:
    """Etkilenen kod parçası."""
    file_path: str
    symbol_name: str
    line_number: int
    dependency_type: DependencyType
    context: str = ""  # Kullanım bağlamı
    reason: str = ""   # Neden etkilendiğinin açıklaması


@dataclass
class ImpactReport:
    """Etki analizi raporu."""
    source_symbol: str
    source_file: str
    affected_codes: List[AffectedCode] = field(default_factory=list)
    total_affected_files: int = 0
    risk_level: str = "low"  # low, medium, high, critical
    summary: str = ""


@dataclass 
class CallGraphNode:
    """Çağrı grafiği düğümü."""
    name: str
    file_path: str
    line_number: int
    callers: List[str] = field(default_factory=list)
    callees: List[str] = field(default_factory=list)


class DependencyTracker:
    """
    Veri yapısı değiştiğinde tüm bağımlı fonksiyonları bulur.
    
    Kritik Özellik:
    Git diff'te görünmeyen ama etkilenen kodları tespit eder ve
    memory'e ekler.
    """
    
    # Aranacak dosya uzantıları
    SUPPORTED_EXTENSIONS = {'.py', '.cpp', '.cc', '.h', '.hpp', '.c', '.js', '.ts'}
    
    # Dışlanacak dizinler
    EXCLUDED_DIRS = {
        'build', '.git', '__pycache__', 'node_modules', 
        '.gradle', '.idea', 'venv', 'env', '.venv'
    }
    
    def __init__(self, root_path: str = "."):
        self.root_path = os.path.abspath(root_path)
        self._symbol_cache: Dict[str, List[str]] = {}
        self._file_cache: Dict[str, str] = {}
    
    def track_data_structure_impact(self, struct_name: str) -> ImpactReport:
        """
        Bir veri yapısının değişmesinin etkisini analiz eder.
        
        Args:
            struct_name: Veri yapısı/struct/class adı
            
        Returns:
            ImpactReport: Etkilenen tüm kodlar
        """
        report = ImpactReport(
            source_symbol=struct_name,
            source_file=""
        )
        
        # Tüm referansları bul
        affected = self._find_all_usages(struct_name)
        report.affected_codes = affected
        report.total_affected_files = len(set(a.file_path for a in affected))
        
        # Risk seviyesi belirle
        if report.total_affected_files > 10:
            report.risk_level = "critical"
        elif report.total_affected_files > 5:
            report.risk_level = "high"
        elif report.total_affected_files > 2:
            report.risk_level = "medium"
        else:
            report.risk_level = "low"
        
        # Özet oluştur
        report.summary = self._generate_impact_summary(report)
        
        return report
    
    def find_ripple_effects(self, changed_symbol: str, file_path: str = None) -> List[AffectedCode]:
        """
        Değişikliğin dalga etkisini hesaplar.
        
        Bir fonksiyon değiştiğinde, o fonksiyonu çağıran tüm kodları bulur,
        sonra onları çağıranları da bulur (2 seviye).
        """
        affected = []
        level_1 = self._find_all_usages(changed_symbol)
        
        for code in level_1:
            code.reason = f"Directly uses '{changed_symbol}'"
            affected.append(code)
            
            # 2. seviye: Bu kodu kullananlar
            if code.symbol_name:
                level_2 = self._find_all_usages(code.symbol_name)
                for l2_code in level_2[:5]:  # Limit to prevent explosion
                    l2_code.reason = f"Indirectly affected via '{code.symbol_name}'"
                    affected.append(l2_code)
        
        return affected
    
    def build_call_graph(self, entry_point: str, file_path: str) -> Dict[str, CallGraphNode]:
        """
        Belirli bir giriş noktasından başlayarak çağrı grafiği oluşturur.
        
        Args:
            entry_point: Başlangıç fonksiyonu
            file_path: Dosya yolu
            
        Returns:
            Dict: Fonksiyon adı -> CallGraphNode 
        """
        graph: Dict[str, CallGraphNode] = {}
        visited: Set[str] = set()
        
        self._build_graph_recursive(entry_point, file_path, graph, visited, depth=0, max_depth=3)
        
        return graph
    
    def get_affected_by_struct_change(self, struct_name: str) -> str:
        """
        Tool wrapper - Bir struct/class'ı kullanan tüm fonksiyonları bulur.
        
        Returns:
            Formatlanmış string çıktı
        """
        report = self.track_data_structure_impact(struct_name)
        
        output = [f"## Impact Analysis: `{struct_name}`\n"]
        output.append(f"**Risk Level**: {report.risk_level.upper()}")
        output.append(f"**Affected Files**: {report.total_affected_files}\n")
        
        if report.affected_codes:
            output.append("### Affected Code Locations:\n")
            
            # Dosyaya göre grupla
            by_file: Dict[str, List[AffectedCode]] = {}
            for code in report.affected_codes:
                if code.file_path not in by_file:
                    by_file[code.file_path] = []
                by_file[code.file_path].append(code)
            
            for fp, codes in list(by_file.items())[:10]:  # İlk 10 dosya
                output.append(f"\n**{fp}**:")
                for code in codes[:5]:  # Her dosyadan max 5 referans
                    output.append(f"  - Line {code.line_number}: `{code.symbol_name or 'usage'}` ({code.dependency_type.value})")
                    if code.context:
                        output.append(f"    ```{code.context[:100]}...```")
        else:
            output.append("No usages found.")
        
        output.append(f"\n{report.summary}")
        
        return '\n'.join(output)
    
    def _find_all_usages(self, symbol_name: str) -> List[AffectedCode]:
        """Sembol kullanımlarını grep ile bulur."""
        affected = []
        
        try:
            cmd = [
                "grep", "-rnI",
                "--include=*.py", "--include=*.cpp", "--include=*.h",
                "--include=*.cc", "--include=*.hpp", "--include=*.js",
                "--exclude-dir=build",
                "--exclude-dir=.git",
                "--exclude-dir=__pycache__",
                "--exclude-dir=node_modules",
                symbol_name,
                self.root_path
            ]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.strip().split('\n')[:50]:  # Max 50 sonuç
                    match = re.match(r'^([^:]+):(\d+):(.*)$', line)
                    if match:
                        file_path = match.group(1)
                        line_no = int(match.group(2))
                        context = match.group(3).strip()
                        
                        # Kullanım tipini belirle
                        dep_type = self._classify_usage(context, symbol_name)
                        
                        # İçinde bulunduğu fonksiyonu bul
                        containing_func = self._find_containing_function(file_path, line_no)
                        
                        affected.append(AffectedCode(
                            file_path=file_path,
                            symbol_name=containing_func,
                            line_number=line_no,
                            dependency_type=dep_type,
                            context=context
                        ))
                        
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            pass
        
        return affected
    
    def _classify_usage(self, context: str, symbol_name: str) -> DependencyType:
        """Kullanım tipini sınıflandırır."""
        context_lower = context.lower()
        
        if 'import' in context_lower or 'from' in context_lower:
            return DependencyType.IMPORT
        elif f'{symbol_name}(' in context or f'{symbol_name} (' in context:
            return DependencyType.DIRECT_CALL
        elif 'class' in context_lower and f'({symbol_name})' in context:
            return DependencyType.INHERITANCE
        elif ':' in context and symbol_name in context.split(':')[1] if ':' in context else False:
            return DependencyType.TYPE_USAGE
        else:
            return DependencyType.DATA_STRUCTURE
    
    def _find_containing_function(self, file_path: str, target_line: int) -> str:
        """Belirli bir satırı içeren fonksiyonu bulur."""
        try:
            if file_path.endswith('.py'):
                content = self._read_file_cached(file_path)
                if content:
                    return self._find_python_function(content, target_line)
        except:
            pass
        
        return ""
    
    def _find_python_function(self, content: str, target_line: int) -> str:
        """Python dosyasında satırı içeren fonksiyonu bulur."""
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                        if node.lineno <= target_line <= (node.end_lineno or node.lineno + 100):
                            return node.name
            
        except:
            pass
        
        return ""
    
    def _read_file_cached(self, file_path: str) -> Optional[str]:
        """Dosyayı cache'den veya diskten okur."""
        if file_path in self._file_cache:
            return self._file_cache[file_path]
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                self._file_cache[file_path] = content
                return content
        except:
            return None
    
    def _build_graph_recursive(
        self, 
        func_name: str,
        file_path: str, 
        graph: Dict[str, CallGraphNode],
        visited: Set[str],
        depth: int,
        max_depth: int
    ):
        """Çağrı grafiğini recursive olarak oluşturur."""
        if depth >= max_depth or func_name in visited:
            return
        
        visited.add(func_name)
        
        # Bu fonksiyonun çağırdıklarını bul
        callees = self._find_callees(func_name, file_path)
        
        # Bu fonksiyonu çağıranları bul
        callers = [
            a.symbol_name for a in self._find_all_usages(func_name)
            if a.symbol_name and a.dependency_type == DependencyType.DIRECT_CALL
        ]
        
        graph[func_name] = CallGraphNode(
            name=func_name,
            file_path=file_path,
            line_number=0,
            callers=callers[:10],
            callees=callees[:10]
        )
        
        # Recursive devam
        for callee in callees[:5]:
            self._build_graph_recursive(callee, file_path, graph, visited, depth + 1, max_depth)
    
    def _find_callees(self, func_name: str, file_path: str) -> List[str]:
        """Bir fonksiyonun çağırdığı diğer fonksiyonları bulur."""
        callees = []
        
        content = self._read_file_cached(file_path)
        if not content or not file_path.endswith('.py'):
            return callees
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == func_name:
                        # Bu fonksiyon içindeki çağrıları bul
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call):
                                if isinstance(child.func, ast.Name):
                                    callees.append(child.func.id)
                                elif isinstance(child.func, ast.Attribute):
                                    callees.append(child.func.attr)
                        break
                        
        except:
            pass
        
        return list(set(callees))
    
    def _generate_impact_summary(self, report: ImpactReport) -> str:
        """Etki özeti oluşturur."""
        parts = []
        
        parts.append(f"### Impact Summary for `{report.source_symbol}`")
        
        if report.risk_level == "critical":
            parts.append("⚠️ **CRITICAL**: This change affects many parts of the codebase!")
        elif report.risk_level == "high":
            parts.append("⚠️ **HIGH RISK**: Significant impact expected.")
        
        parts.append(f"\n- **Total affected files**: {report.total_affected_files}")
        parts.append(f"- **Total affected locations**: {len(report.affected_codes)}")
        
        # Dependency type breakdown
        type_counts: Dict[DependencyType, int] = {}
        for code in report.affected_codes:
            type_counts[code.dependency_type] = type_counts.get(code.dependency_type, 0) + 1
        
        if type_counts:
            parts.append("\n**Usage breakdown**:")
            for dep_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                parts.append(f"  - {dep_type.value}: {count}")
        
        return '\n'.join(parts)


def find_affected_by_struct(struct_name: str, root_path: str = ".") -> str:
    """
    Tool wrapper - Bir veri yapısını kullanan tüm fonksiyonları bulur.
    
    Args:
        struct_name: Struct/class adı
        root_path: Arama kök dizini
        
    Returns:
        Formatlanmış analiz sonucu
    """
    tracker = DependencyTracker(root_path)
    return tracker.get_affected_by_struct_change(struct_name)


def find_ripple_effects(symbol_name: str, root_path: str = ".") -> str:
    """
    Tool wrapper - Değişikliğin dalga etkisini hesaplar.
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
    
    return '\n'.join(output)
