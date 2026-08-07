"""
Review Gate - CI Pipeline Kontrol Mekanizması.

Agent'ın review sonucuna göre pipeline'ın devam edip etmeyeceğine karar verir.
Markdown çıktısını parse ederek metrikleri ve bulguları değerlendirir.
"""

import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from ..config.config_loader import ReviewPolicy


class ReviewGateResult(Enum):
    """Pipeline karar sonucu."""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class GateEvaluation:
    """Gate değerlendirme sonucu."""
    result: ReviewGateResult
    exit_code: int
    reasons: List[str]
    scores: Dict[str, int]
    blocking_issues: List[str]


class ReviewGate:
    """
    Review sonucunu değerlendiren mekanizma.
    
    Kontrol edilen kriterler:
    - SAST Scan Result (Pass/Fail)
    - Security Risk Level (Critical/High)
    - Breaking Changes
    - Code Quality Score
    - Performance Issues
    """
    
    def __init__(self, policy: ReviewPolicy):
        self.policy = policy
    
    def evaluate(self, review_markdown: str) -> GateEvaluation:
        """
        Agent'ın markdown çıktısını analiz eder ve karar verir.
        
        Args:
            review_markdown: Agent'ın ürettiği markdown raporu
            
        Returns:
            GateEvaluation: Değerlendirme sonucu
        """
        reasons = []
        blocking_issues = []
        scores = {}
        
        # 1. SAST/Security Kontrolü
        security_score = 100  # Default
        sast_fail = False
        
        if "SAST Scan Result: FAIL" in review_markdown:
            sast_fail = True
            reasons.append("SAST Scan Failed")
            security_score = 0  # Fail ise 0 kabul ediyoruz
        
        # Risk seviyesini parse et
        risk_match = re.search(r"Risk Assessment\*\*:\s*\[?(\w+)\]?", review_markdown)
        risk_level = risk_match.group(1).lower() if risk_match else "unknown"
        
        if risk_level == "critical" and self.policy.gate.fail_pipeline_on_critical:
            blocking_issues.append("Critical Risk Assessment")
        
        # 2. Quality Score Parsing
        quality_match = re.search(r"SOLID Compliance\*\*:\s*\[?(\d+)/100\]?", review_markdown)
        quality_score = int(quality_match.group(1)) if quality_match else 0
        scores['quality'] = quality_score
        
        if quality_score < self.policy.gate.quality_score_threshold:
            msg = f"Quality Score ({quality_score}) below threshold ({self.policy.gate.quality_score_threshold})"
            if self.policy.gate.fail_pipeline_on_quality_below > quality_score:
                blocking_issues.append(msg)
            else:
                reasons.append(msg)
        
        # 3. Breaking Changes
        if "Breaking Changes**: Yes" in review_markdown:
            msg = "Breaking Changes Detected"
            if self.policy.security.block_on_critical: # Breaking change kritik kabul edilebilir
                reasons.append(msg)
        
        # 4. Karar Verme
        result = ReviewGateResult.PASS
        exit_code = 0
        
        if blocking_issues or sast_fail:
            result = ReviewGateResult.FAIL
            exit_code = 1
            reasons.extend(blocking_issues)
        elif reasons:
            result = ReviewGateResult.WARN
            exit_code = 0  # Warning pipeline'ı kırmaz (opsiyonel)
        
        return GateEvaluation(
            result=result,
            exit_code=exit_code,
            reasons=reasons,
            scores=scores,
            blocking_issues=blocking_issues
        )
