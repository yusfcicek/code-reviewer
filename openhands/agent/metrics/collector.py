"""
Metrics Collector - Review Metriklerini Toplama ve Raporlama.

Prometheus ve GitLab metrics formatları için çıktı üretir.
Quality, Security ve Performance trendlerini takip eder.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional

from ..triage.review_triage import ReviewDecision


@dataclass
class ReviewMetrics:
    """Tek bir review işlemi için metrikler."""
    project_id: str
    mr_id: str
    timestamp: float = field(default_factory=time.time)
    
    # Kapsam
    files_analyzed: int = 0
    lines_analyzed: int = 0
    
    # Kararlar
    triage_decisions: Dict[str, int] = field(default_factory=lambda: {d.value: 0 for d in ReviewDecision})
    gate_result: str = "pass"
    
    # Skorlar
    quality_score: int = 0
    security_score: int = 0
    performance_score: int = 0
    
    # Bulgular
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    
    # Performans
    duration_ms: int = 0


class MetricsCollector:
    """
    Review metriklerini toplar ve export eder.
    """
    
    def __init__(self):
        self._metrics: List[ReviewMetrics] = []
    
    def record(self, metrics: ReviewMetrics):
        """Metrik kaydeder."""
        self._metrics.append(metrics)
    
    def export_prometheus(self) -> str:
        """Prometheus formatında metrikleri döner."""
        lines = []
        
        # Son eklenen metrikleri kullan
        if not self._metrics:
            return ""
            
        latest = self._metrics[-1]
        labels = f'project_id="{latest.project_id}",mr_id="{latest.mr_id}"'
        
        # Quality Scores
        lines.append(f'code_review_quality_score{{{labels}}} {latest.quality_score}')
        lines.append(f'code_review_security_score{{{labels}}} {latest.security_score}')
        lines.append(f'code_review_performance_score{{{labels}}} {latest.performance_score}')
        
        # Issues
        lines.append(f'code_review_critical_issues{{{labels}}} {latest.critical_issues}')
        lines.append(f'code_review_high_issues{{{labels}}} {latest.high_issues}')
        
        # Gate
        gate_val = 1 if latest.gate_result == "pass" else 0
        lines.append(f'code_review_gate_passed{{{labels}}} {gate_val}')
        
        # Duration
        lines.append(f'code_review_duration_ms{{{labels}}} {latest.duration_ms}')
        
        return '\n'.join(lines)
    
    def export_gitlab_metrics(self, file_path: str = "metrics.txt"):
        """GitLab CI openmetrics formatında dosyaya yazar."""
        content = self.export_prometheus()
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print(f"Error exporting metrics to {file_path}: {e}")
    
    def export_json(self, file_path: str = "review_metrics.json"):
        """JSON formatında kaydeder."""
        data = [asdict(m) for m in self._metrics]
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error exporting JSON metrics: {e}")
