"""
Memory Strategies - Gelişmiş bellek yönetimi stratejileri.

Token-aware, priority-based memory yönetimi:
- Kritik bilgilerin korunması
- Otomatik özetleme
- Etkilenen kod takibi
- Chunk-based dosya okuma
"""

from typing import Any, List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from openhands.agent.core.interfaces import MemoryStrategy, LLMProvider


class InsightPriority(Enum):
    """Insight öncelik seviyesi."""
    CRITICAL = "critical"    # Asla özetlenmez (breaking changes, security)
    HIGH = "high"            # Son özetlenir
    NORMAL = "normal"        # Normal özetleme
    LOW = "low"              # İlk özetlenir


@dataclass
class MemoryInsight:
    """Yapılandırılmış memory insight."""
    content: str
    priority: InsightPriority = InsightPriority.NORMAL
    category: str = "GENERAL"
    source_file: str = ""
    tokens: int = 0


@dataclass
class AffectedCodeEntry:
    """Git diff dışında etkilenen kod."""
    file_path: str
    symbol_name: str
    reason: str  # Neden etkilendiği
    content_preview: str = ""
    line_number: int = 0


class SmartMemoryStrategy(MemoryStrategy):
    """
    Token-aware, priority-based memory yönetimi.
    
    Özellikler:
    - Kritik bilgileri korur (güvenlik, breaking changes)
    - Gerektiğinde otomatik özetleme
    - Git diff dışı etkilenen kodları takip eder
    - Büyük dosyaları chunk'lar halinde işler
    """
    
    # Default token limits
    DEFAULT_MAX_TOKENS = 100000
    SUMMARIZE_THRESHOLD = 0.8  # %80 dolulukta özetleme başlat
    CRITICAL_RESERVED = 10000  # Kritik bilgiler için rezerv
    
    # Kategori -> Priority mapping
    CATEGORY_PRIORITIES = {
        "SECURITY": InsightPriority.CRITICAL,
        "BREAKING": InsightPriority.CRITICAL,
        "CRITICAL": InsightPriority.CRITICAL,
        "RISK": InsightPriority.HIGH,
        "DEPENDENCY": InsightPriority.HIGH,
        "AFFECTED_CODE": InsightPriority.HIGH,
        "PERFORMANCE": InsightPriority.NORMAL,
        "PATTERN": InsightPriority.NORMAL,
        "QUALITY": InsightPriority.NORMAL,
        "TODO": InsightPriority.LOW,
        "GENERAL": InsightPriority.LOW,
    }
    
    def __init__(self, llm_provider: LLMProvider, max_tokens: int = None):
        import types
        self.llm = llm_provider.get_chat_model()
        self.max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS
        
        # Offline token counting
        def offline_get_num_tokens(self, messages: list) -> int:
            total_chars = 0
            for m in messages:
                if hasattr(m, 'content'):
                    total_chars += len(m.content)
                else:
                    total_chars += len(str(m))
            return int(total_chars / 4)
        
        object.__setattr__(self.llm, 'get_num_tokens_from_messages', 
                          types.MethodType(offline_get_num_tokens, self.llm))
        
        # Priority-based insight storage
        self.critical_insights: List[MemoryInsight] = []   # Never summarized
        self.high_insights: List[MemoryInsight] = []       # Summarized last
        self.normal_insights: List[MemoryInsight] = []     # Normal summarization
        self.low_insights: List[MemoryInsight] = []        # Summarized first
        
        # Affected code tracking (git diff dışı)
        self.affected_codes: List[AffectedCodeEntry] = []
        
        # File chunks for large files
        self.file_chunks: Dict[str, List[str]] = {}
        
        # Summarization state
        self.summary_buffer: str = ""
        self.total_tokens_used: int = 0
        self.summarization_count: int = 0
    
    def log_insight(self, insight: str):
        """
        Insight'ı uygun priority ile kaydeder.
        
        Format: [CATEGORY] message
        Örnek: [SECURITY] SQL injection found in user_input.py
        """
        # Parse category from insight
        category = "GENERAL"
        content = insight
        
        import re
        match = re.match(r'\[(\w+)\]\s*(.*)', insight)
        if match:
            category = match.group(1).upper()
            content = match.group(2)
        
        # Determine priority
        priority = self.CATEGORY_PRIORITIES.get(category, InsightPriority.NORMAL)
        
        # Estimate tokens
        tokens = len(insight) // 4
        
        # Create insight object
        memory_insight = MemoryInsight(
            content=insight,
            priority=priority,
            category=category,
            tokens=tokens
        )
        
        # Store in appropriate list
        if priority == InsightPriority.CRITICAL:
            if insight not in [i.content for i in self.critical_insights]:
                self.critical_insights.append(memory_insight)
        elif priority == InsightPriority.HIGH:
            if insight not in [i.content for i in self.high_insights]:
                self.high_insights.append(memory_insight)
        elif priority == InsightPriority.NORMAL:
            if insight not in [i.content for i in self.normal_insights]:
                self.normal_insights.append(memory_insight)
        else:
            if insight not in [i.content for i in self.low_insights]:
                self.low_insights.append(memory_insight)
        
        self._update_token_count()
    
    def add_affected_code(self, file_path: str, symbol_name: str, reason: str, 
                          content_preview: str = "", line_number: int = 0):
        """
        Git diff'te görünmeyen ama etkilenen kodu memory'e ekler.
        
        Args:
            file_path: Etkilenen dosya yolu
            symbol_name: Fonksiyon/sınıf adı
            reason: Neden etkilendiği (örn: 'data_structure_dependency')
            content_preview: İlgili kod parçası
            line_number: Satır numarası
        """
        entry = AffectedCodeEntry(
            file_path=file_path,
            symbol_name=symbol_name,
            reason=reason,
            content_preview=content_preview[:200] if content_preview else "",
            line_number=line_number
        )
        
        # Duplicate check
        existing = [e for e in self.affected_codes 
                   if e.file_path == file_path and e.symbol_name == symbol_name]
        if not existing:
            self.affected_codes.append(entry)
            
            # Also add as high priority insight
            insight = f"[AFFECTED_CODE] {file_path}:{symbol_name} - {reason}"
            self.log_insight(insight)
    
    def load_context(self) -> str:
        """
        Öncelik sırasına göre context string oluşturur.
        Kritik bilgiler her zaman dahil edilir.
        """
        parts = ["# SMART MEMORY CONTEXT\n"]
        
        # Critical insights - always included
        if self.critical_insights:
            parts.append("\n## 🚨 CRITICAL (Never Summarized)")
            for insight in self.critical_insights:
                parts.append(f"- {insight.content}")
        
        # High priority
        if self.high_insights:
            parts.append("\n## ⚠️ HIGH PRIORITY")
            for insight in self.high_insights[:20]:  # Limit display
                parts.append(f"- {insight.content}")
        
        # Affected codes (git diff dışı)
        if self.affected_codes:
            parts.append("\n## 🔗 AFFECTED CODE (Not in Git Diff)")
            for entry in self.affected_codes[:10]:
                parts.append(f"- `{entry.file_path}:{entry.symbol_name}` - {entry.reason}")
                if entry.content_preview:
                    parts.append(f"  ```\n  {entry.content_preview}\n  ```")
        
        # Normal & low priority (if space available)
        remaining_tokens = self.max_tokens - self._estimate_context_tokens(parts)
        
        if remaining_tokens > 5000:
            if self.normal_insights:
                parts.append("\n## 📋 NORMAL PRIORITY")
                for insight in self.normal_insights[:15]:
                    parts.append(f"- {insight.content}")
        
        # Summary buffer if exists
        if self.summary_buffer:
            parts.append("\n## 📝 SUMMARIZED CONTEXT")
            parts.append(self.summary_buffer)
        
        # Token status
        parts.append(f"\n---\n*Memory usage: {self.total_tokens_used}/{self.max_tokens} tokens*")
        
        return "\n".join(parts)
    
    def summarize_if_needed(self) -> bool:
        """
        Token limiti aşıldığında otomatik özetleme yapar.
        
        Returns:
            bool: Özetleme yapıldı mı
        """
        self._update_token_count()
        threshold = int(self.max_tokens * self.SUMMARIZE_THRESHOLD)
        
        if self.total_tokens_used < threshold:
            return False
        
        print(f"[MEMORY] Summarization triggered. Usage: {self.total_tokens_used}/{self.max_tokens}")
        
        # Summarize in order: low -> normal -> high (never critical)
        summarized = False
        
        # First, summarize LOW priority
        if self.low_insights and len(self.low_insights) > 3:
            summary = self._create_summary(self.low_insights)
            self.summary_buffer += f"\n### Low Priority Summary:\n{summary}\n"
            self.low_insights = self.low_insights[-2:]  # Keep last 2
            summarized = True
        
        # Then NORMAL priority if still over threshold
        self._update_token_count()
        if self.total_tokens_used > threshold and self.normal_insights and len(self.normal_insights) > 5:
            summary = self._create_summary(self.normal_insights)
            self.summary_buffer += f"\n### Normal Priority Summary:\n{summary}\n"
            self.normal_insights = self.normal_insights[-3:]  # Keep last 3
            summarized = True
        
        # HIGH priority only if critical
        self._update_token_count()
        critical_threshold = int(self.max_tokens * 0.95)
        if self.total_tokens_used > critical_threshold and self.high_insights and len(self.high_insights) > 10:
            summary = self._create_summary(self.high_insights)
            self.summary_buffer += f"\n### High Priority Summary:\n{summary}\n"
            self.high_insights = self.high_insights[-5:]  # Keep last 5
            summarized = True
        
        if summarized:
            self.summarization_count += 1
            self._update_token_count()
            print(f"[MEMORY] After summarization: {self.total_tokens_used}/{self.max_tokens}")
        
        return summarized
    
    def _create_summary(self, insights: List[MemoryInsight]) -> str:
        """Insight listesini özetler."""
        content = "\n".join([i.content for i in insights])
        
        # Simple summary - in production, use LLM
        # For now, just compress by removing details
        lines = content.split('\n')
        if len(lines) > 10:
            summary_lines = lines[:3] + ["...[summarized]..."] + lines[-3:]
            return "\n".join(summary_lines)
        
        return content
    
    def chunk_large_file(self, content: str, file_path: str, 
                         chunk_size: int = 2000) -> List[str]:
        """
        Büyük dosyayı chunk'lara ayırır ve cache'ler.
        
        Args:
            content: Dosya içeriği
            file_path: Dosya yolu
            chunk_size: Chunk başına karakter sayısı
            
        Returns:
            List[str]: Chunk listesi
        """
        if file_path in self.file_chunks:
            return self.file_chunks[file_path]
        
        lines = content.split('\n')
        chunks = []
        current_chunk = []
        current_size = 0
        
        for line in lines:
            line_size = len(line) + 1  # +1 for newline
            
            if current_size + line_size > chunk_size and current_chunk:
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_size = 0
            
            current_chunk.append(line)
            current_size += line_size
        
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        self.file_chunks[file_path] = chunks
        return chunks
    
    def get_priority_context(self) -> str:
        """
        Sadece kritik ve yüksek öncelikli bilgileri döner.
        Token tasarrufu için kullanılır.
        """
        parts = ["# PRIORITY CONTEXT (Token-Optimized)\n"]
        
        if self.critical_insights:
            parts.append("\n## 🚨 CRITICAL")
            for insight in self.critical_insights:
                parts.append(f"- {insight.content}")
        
        if self.affected_codes:
            parts.append("\n## 🔗 AFFECTED (Not in Diff)")
            for entry in self.affected_codes[:5]:
                parts.append(f"- `{entry.file_path}:{entry.symbol_name}`")
        
        return "\n".join(parts)
    
    def save_context(self, input_text: str, output_text: str) -> None:
        """Context'i kaydeder ve gerekirse özetler."""
        # Check for memory triggers
        self.summarize_if_needed()
    
    def get_memory_object(self) -> Any:
        return None  # Bu strateji LangChain memory kullanmıyor
    
    def _update_token_count(self):
        """Toplam token kullanımını günceller."""
        total = 0
        
        for insight in self.critical_insights:
            total += insight.tokens
        for insight in self.high_insights:
            total += insight.tokens
        for insight in self.normal_insights:
            total += insight.tokens
        for insight in self.low_insights:
            total += insight.tokens
        
        total += len(self.summary_buffer) // 4
        
        for entry in self.affected_codes:
            total += len(str(entry)) // 4
        
        self.total_tokens_used = total
    
    def _estimate_context_tokens(self, parts: List[str]) -> int:
        """Context parçalarının token sayısını tahmin eder."""
        return sum(len(p) // 4 for p in parts)
    
    def get_stats(self) -> Dict:
        """Memory istatistiklerini döner."""
        return {
            "total_tokens": self.total_tokens_used,
            "max_tokens": self.max_tokens,
            "usage_percent": (self.total_tokens_used / self.max_tokens) * 100,
            "critical_count": len(self.critical_insights),
            "high_count": len(self.high_insights),
            "normal_count": len(self.normal_insights),
            "low_count": len(self.low_insights),
            "affected_code_count": len(self.affected_codes),
            "summarization_count": self.summarization_count
        }

