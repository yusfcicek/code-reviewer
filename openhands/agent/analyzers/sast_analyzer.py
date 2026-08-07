"""
SAST Analyzer - Statik Uygulama Güvenlik Testi.

Güvenlik açıkları için statik kod analizi yapar:
- SQL Injection
- XSS (Cross-Site Scripting)
- Command Injection
- Hardcoded Secrets
- Path Traversal
- Insecure Random
- Missing Input Validation
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Pattern, Tuple, Optional


class Severity(Enum):
    """Güvenlik bulgusu şiddeti."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class VulnerabilityType(Enum):
    """Güvenlik açığı tipleri."""
    SQL_INJECTION = "sql_injection"
    XSS = "xss"
    COMMAND_INJECTION = "command_injection"
    PATH_TRAVERSAL = "path_traversal"
    HARDCODED_SECRET = "hardcoded_secret"
    INSECURE_RANDOM = "insecure_random"
    INSECURE_DESERIALIZATION = "insecure_deserialization"
    WEAK_CRYPTO = "weak_crypto"
    MISSING_INPUT_VALIDATION = "missing_input_validation"
    INSECURE_FILE_OPERATION = "insecure_file_operation"
    DEBUG_CODE = "debug_code"
    SENSITIVE_DATA_EXPOSURE = "sensitive_data_exposure"
    INSECURE_HTTP = "insecure_http"


@dataclass
class SecurityFinding:
    """Güvenlik bulgusu."""
    vulnerability_type: VulnerabilityType
    severity: Severity
    line_number: int
    line_content: str
    description: str
    recommendation: str
    cwe_id: str = ""  # Common Weakness Enumeration
    owasp_category: str = ""  # OWASP Top 10 kategori


@dataclass
class RiskScore:
    """Risk skoru."""
    total_score: int  # 0-100
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    risk_level: str  # "critical", "high", "medium", "low", "safe"


@dataclass
class SASTReport:
    """SAST analiz raporu."""
    file_path: str
    findings: List[SecurityFinding] = field(default_factory=list)
    risk_score: Optional[RiskScore] = None
    summary: str = ""
    scan_coverage: float = 100.0


class SASTAnalyzer:
    """
    Güvenlik açıkları için statik kod analizi.
    
    OWASP Top 10 ve CWE tabanlı güvenlik kontrolleri yapar.
    """
    
    # Python güvenlik pattern'leri
    PYTHON_PATTERNS: Dict[VulnerabilityType, List[Tuple[str, Severity, str, str, str]]] = {
        VulnerabilityType.SQL_INJECTION: [
            (r'execute\s*\([^)]*\+', Severity.CRITICAL, 
             "SQL query built with string concatenation",
             "Use parameterized queries with placeholders",
             "CWE-89"),
            (r'cursor\.execute\s*\(\s*f["\']', Severity.CRITICAL,
             "SQL query uses f-string formatting",
             "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
             "CWE-89"),
            (r'\.execute\s*\(\s*["\'].*%s.*["\'].*%', Severity.HIGH,
             "SQL query uses % formatting",
             "Use parameterized queries instead of % formatting",
             "CWE-89"),
            (r'\.raw\s*\([^)]*\+', Severity.CRITICAL,
             "Django raw query with string concatenation",
             "Use QuerySet methods or parameterized raw queries",
             "CWE-89"),
        ],
        
        VulnerabilityType.XSS: [
            (r'innerHTML\s*=', Severity.HIGH,
             "Direct innerHTML assignment may allow XSS",
             "Use textContent or sanitize input before using innerHTML",
             "CWE-79"),
            (r'document\.write\s*\(', Severity.HIGH,
             "document.write can lead to XSS",
             "Use DOM manipulation methods instead",
             "CWE-79"),
            (r'\.html\s*\([^)]*\+', Severity.MEDIUM,
             "jQuery .html() with string concatenation",
             "Use .text() or sanitize input",
             "CWE-79"),
            (r'mark_safe\s*\([^)]*\+', Severity.HIGH,
             "Django mark_safe with concatenation is dangerous",
             "Validate and escape content before marking as safe",
             "CWE-79"),
        ],
        
        VulnerabilityType.COMMAND_INJECTION: [
            (r'os\.system\s*\([^)]*\+', Severity.CRITICAL,
             "os.system with string concatenation allows command injection",
             "Use subprocess with shell=False and argument list",
             "CWE-78"),
            (r'subprocess\.\w+\s*\([^)]*shell\s*=\s*True', Severity.HIGH,
             "subprocess with shell=True is vulnerable to injection",
             "Use shell=False with argument list",
             "CWE-78"),
            (r'eval\s*\(', Severity.CRITICAL,
             "eval() executes arbitrary code",
             "Avoid eval(). Use ast.literal_eval() for data parsing",
             "CWE-95"),
            (r'exec\s*\(', Severity.CRITICAL,
             "exec() executes arbitrary code",
             "Avoid exec(). Find alternative approaches",
             "CWE-95"),
            (r'os\.popen\s*\(', Severity.HIGH,
             "os.popen is vulnerable to command injection",
             "Use subprocess with proper argument handling",
             "CWE-78"),
        ],
        
        VulnerabilityType.PATH_TRAVERSAL: [
            (r'open\s*\([^)]*\.\./', Severity.HIGH,
             "Potential path traversal with ../ in file path",
             "Validate and sanitize file paths. Use os.path.realpath()",
             "CWE-22"),
            (r'os\.path\.join\s*\([^)]*request\.\w+', Severity.MEDIUM,
             "File path constructed from user input",
             "Validate input and use os.path.realpath() to prevent traversal",
             "CWE-22"),
            (r'send_file\s*\([^)]*\+', Severity.HIGH,
             "send_file with user-controlled path",
             "Whitelist allowed files or validate paths strictly",
             "CWE-22"),
        ],
        
        VulnerabilityType.HARDCODED_SECRET: [
            (r'password\s*=\s*["\'][^"\']{3,}["\']', Severity.HIGH,
             "Hardcoded password detected",
             "Use environment variables or secrets manager",
             "CWE-798"),
            (r'api[_-]?key\s*=\s*["\'][^"\']{10,}["\']', Severity.HIGH,
             "Hardcoded API key detected",
             "Store API keys in environment variables",
             "CWE-798"),
            (r'secret[_-]?key\s*=\s*["\'][^"\']{5,}["\']', Severity.HIGH,
             "Hardcoded secret key detected",
             "Use secure secrets management",
             "CWE-798"),
            (r'token\s*=\s*["\'][a-zA-Z0-9]{20,}["\']', Severity.MEDIUM,
             "Possible hardcoded token",
             "Store tokens securely, not in source code",
             "CWE-798"),
            (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', Severity.CRITICAL,
             "Private key embedded in source code",
             "Never commit private keys. Use key management systems",
             "CWE-798"),
        ],
        
        VulnerabilityType.INSECURE_RANDOM: [
            (r'random\.\w+\s*\(', Severity.MEDIUM,
             "random module is not cryptographically secure",
             "Use secrets module for security-sensitive randomness",
             "CWE-330"),
            (r'Math\.random\s*\(', Severity.MEDIUM,
             "Math.random() is not cryptographically secure",
             "Use crypto.getRandomValues() for security purposes",
             "CWE-330"),
        ],
        
        VulnerabilityType.INSECURE_DESERIALIZATION: [
            (r'pickle\.loads?\s*\(', Severity.HIGH,
             "pickle can deserialize malicious data",
             "Avoid pickle for untrusted data. Use JSON or validate source",
             "CWE-502"),
            (r'yaml\.load\s*\([^)]*(?!Loader\s*=)', Severity.HIGH,
             "yaml.load without safe Loader is dangerous",
             "Use yaml.safe_load() or specify Loader=yaml.SafeLoader",
             "CWE-502"),
            (r'marshal\.loads?\s*\(', Severity.HIGH,
             "marshal can execute code during deserialization",
             "Avoid marshal for untrusted data",
             "CWE-502"),
        ],
        
        VulnerabilityType.WEAK_CRYPTO: [
            (r'hashlib\.md5\s*\(', Severity.MEDIUM,
             "MD5 is cryptographically broken",
             "Use SHA-256 or better for security purposes",
             "CWE-327"),
            (r'hashlib\.sha1\s*\(', Severity.LOW,
             "SHA1 is deprecated for security use",
             "Use SHA-256 or better",
             "CWE-327"),
            (r'DES\s*\(|Blowfish\s*\(', Severity.HIGH,
             "Weak encryption algorithm detected",
             "Use AES-256 or ChaCha20",
             "CWE-327"),
        ],
        
        VulnerabilityType.DEBUG_CODE: [
            (r'print\s*\([^)]*password', Severity.HIGH,
             "Sensitive data being printed",
             "Remove debug logging of sensitive information",
             "CWE-532"),
            (r'DEBUG\s*=\s*True', Severity.MEDIUM,
             "Debug mode enabled",
             "Disable debug mode in production",
             "CWE-489"),
            (r'import\s+pdb|pdb\.set_trace\s*\(', Severity.MEDIUM,
             "Debugger code left in source",
             "Remove debugger breakpoints before deployment",
             "CWE-489"),
        ],
        
        VulnerabilityType.INSECURE_HTTP: [
            (r'http://[^"\'\s]+', Severity.LOW,
             "Insecure HTTP URL detected",
             "Use HTTPS for secure communication",
             "CWE-319"),
            (r'verify\s*=\s*False', Severity.HIGH,
             "SSL verification disabled",
             "Enable SSL verification: verify=True",
             "CWE-295"),
        ],
        
        VulnerabilityType.INSECURE_FILE_OPERATION: [
            (r'chmod\s*\([^)]*0?777', Severity.MEDIUM,
             "File permissions set to world-writable",
             "Use more restrictive permissions (e.g., 0o644)",
             "CWE-732"),
            (r'open\s*\([^)]+,\s*["\']w["\']', Severity.LOW,
             "File opened for writing - ensure path validation",
             "Validate file paths before writing",
             "CWE-73"),
        ],
    }
    
    # C/C++ güvenlik pattern'leri  
    CPP_PATTERNS: Dict[VulnerabilityType, List[Tuple[str, Severity, str, str, str]]] = {
        VulnerabilityType.COMMAND_INJECTION: [
            (r'system\s*\(', Severity.HIGH,
             "system() call is vulnerable to injection",
             "Use exec family functions with validated input",
             "CWE-78"),
            (r'popen\s*\(', Severity.HIGH,
             "popen() is vulnerable to command injection",
             "Use exec family or validate input strictly",
             "CWE-78"),
        ],
        
        VulnerabilityType.SQL_INJECTION: [
            (r'sprintf\s*\([^)]*SELECT', Severity.CRITICAL,
             "SQL query built with sprintf",
             "Use prepared statements/parameterized queries",
             "CWE-89"),
        ],
        
        VulnerabilityType.INSECURE_FILE_OPERATION: [
            (r'strcpy\s*\(', Severity.HIGH,
             "strcpy is vulnerable to buffer overflow",
             "Use strncpy or strlcpy with bounds checking",
             "CWE-120"),
            (r'sprintf\s*\(', Severity.MEDIUM,
             "sprintf can cause buffer overflow",
             "Use snprintf with size limit",
             "CWE-120"),
            (r'gets\s*\(', Severity.CRITICAL,
             "gets() is extremely dangerous - no bounds checking",
             "Use fgets() with buffer size limit",
             "CWE-120"),
        ],
        
        VulnerabilityType.WEAK_CRYPTO: [
            (r'rand\s*\(', Severity.MEDIUM,
             "rand() is not cryptographically secure",
             "Use /dev/urandom or platform secure random",
             "CWE-330"),
        ],
    }
    
    def __init__(self):
        self._compiled_patterns: Dict[str, Dict[VulnerabilityType, List]] = {}
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Pattern'leri regex olarak compile eder."""
        self._compiled_patterns['python'] = {}
        for vuln_type, patterns in self.PYTHON_PATTERNS.items():
            self._compiled_patterns['python'][vuln_type] = [
                (re.compile(p[0], re.IGNORECASE), p[1], p[2], p[3], p[4])
                for p in patterns
            ]
        
        self._compiled_patterns['cpp'] = {}
        for vuln_type, patterns in self.CPP_PATTERNS.items():
            self._compiled_patterns['cpp'][vuln_type] = [
                (re.compile(p[0], re.IGNORECASE), p[1], p[2], p[3], p[4])
                for p in patterns
            ]
    
    def analyze(self, content: str, file_path: str = "") -> SASTReport:
        """
        Kod içeriğini güvenlik açıkları için analiz eder.
        
        Args:
            content: Dosya içeriği
            file_path: Dosya yolu
            
        Returns:
            SASTReport: Güvenlik analiz raporu
        """
        report = SASTReport(file_path=file_path)
        
        # Dil tespiti
        lang = self._detect_language(file_path)
        
        # Satır satır analiz
        lines = content.split('\n')
        for line_num, line in enumerate(lines, 1):
            # Yorum satırlarını atla
            if self._is_comment(line, lang):
                continue
            
            # Pattern'leri kontrol et
            findings = self._check_line(line, line_num, lang)
            report.findings.extend(findings)
        
        # Risk skoru hesapla
        report.risk_score = self.calculate_risk_score(report.findings)
        
        # Özet oluştur
        report.summary = self._generate_summary(report)
        
        return report
    
    def _detect_language(self, file_path: str) -> str:
        """Dosya uzantısından dil tespit eder."""
        if file_path.endswith('.py'):
            return 'python'
        elif file_path.endswith(('.cpp', '.cc', '.c', '.h', '.hpp')):
            return 'cpp'
        elif file_path.endswith(('.js', '.ts')):
            return 'javascript'
        return 'python'  # Default
    
    def _is_comment(self, line: str, lang: str) -> bool:
        """Satırın yorum olup olmadığını kontrol eder."""
        stripped = line.strip()
        
        if lang == 'python':
            return stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''")
        elif lang in ['cpp', 'javascript']:
            return stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*')
        
        return False
    
    def _check_line(self, line: str, line_num: int, lang: str) -> List[SecurityFinding]:
        """Tek satırı tüm pattern'lerle kontrol eder."""
        findings = []
        
        patterns = self._compiled_patterns.get(lang, self._compiled_patterns['python'])
        
        for vuln_type, pattern_list in patterns.items():
            for pattern, severity, desc, recommendation, cwe_id in pattern_list:
                if pattern.search(line):
                    findings.append(SecurityFinding(
                        vulnerability_type=vuln_type,
                        severity=severity,
                        line_number=line_num,
                        line_content=line.strip()[:100],
                        description=desc,
                        recommendation=recommendation,
                        cwe_id=cwe_id,
                        owasp_category=self._get_owasp_category(vuln_type)
                    ))
        
        return findings
    
    def _get_owasp_category(self, vuln_type: VulnerabilityType) -> str:
        """OWASP Top 10 kategorisini döner."""
        owasp_mapping = {
            VulnerabilityType.SQL_INJECTION: "A03:2021 - Injection",
            VulnerabilityType.XSS: "A03:2021 - Injection",
            VulnerabilityType.COMMAND_INJECTION: "A03:2021 - Injection",
            VulnerabilityType.PATH_TRAVERSAL: "A01:2021 - Broken Access Control",
            VulnerabilityType.HARDCODED_SECRET: "A02:2021 - Cryptographic Failures",
            VulnerabilityType.INSECURE_RANDOM: "A02:2021 - Cryptographic Failures",
            VulnerabilityType.INSECURE_DESERIALIZATION: "A08:2021 - Software and Data Integrity Failures",
            VulnerabilityType.WEAK_CRYPTO: "A02:2021 - Cryptographic Failures",
            VulnerabilityType.DEBUG_CODE: "A05:2021 - Security Misconfiguration",
            VulnerabilityType.INSECURE_HTTP: "A02:2021 - Cryptographic Failures",
        }
        return owasp_mapping.get(vuln_type, "")
    
    def calculate_risk_score(self, findings: List[SecurityFinding]) -> RiskScore:
        """
        Bulgulara göre risk skoru hesaplar.
        
        Scoring:
        - Critical: 25 puan
        - High: 15 puan  
        - Medium: 5 puan
        - Low: 2 puan
        """
        severity_weights = {
            Severity.CRITICAL: 25,
            Severity.HIGH: 15,
            Severity.MEDIUM: 5,
            Severity.LOW: 2,
            Severity.INFO: 0
        }
        
        counts = {s: 0 for s in Severity}
        total = 0
        
        for finding in findings:
            counts[finding.severity] += 1
            total += severity_weights.get(finding.severity, 0)
        
        # Risk seviyesi
        if total >= 100 or counts[Severity.CRITICAL] > 0:
            risk_level = "critical"
        elif total >= 50 or counts[Severity.HIGH] >= 3:
            risk_level = "high"
        elif total >= 20 or counts[Severity.HIGH] >= 1:
            risk_level = "medium"
        elif total > 0:
            risk_level = "low"
        else:
            risk_level = "safe"
        
        return RiskScore(
            total_score=min(100, total),
            critical_count=counts[Severity.CRITICAL],
            high_count=counts[Severity.HIGH],
            medium_count=counts[Severity.MEDIUM],
            low_count=counts[Severity.LOW],
            risk_level=risk_level
        )
    
    def _generate_summary(self, report: SASTReport) -> str:
        """SAST rapor özeti oluşturur."""
        parts = []
        
        if not report.findings:
            parts.append("✅ No security vulnerabilities detected.")
            return '\n'.join(parts)
        
        risk = report.risk_score
        
        # Risk seviyesi emoji
        risk_emoji = {
            "critical": "🚨",
            "high": "⚠️",
            "medium": "⚡",
            "low": "ℹ️",
            "safe": "✅"
        }
        
        parts.append(f"{risk_emoji.get(risk.risk_level, '')} **Security Risk Level**: {risk.risk_level.upper()}")
        parts.append(f"**Risk Score**: {risk.total_score}/100\n")
        
        parts.append("**Findings by Severity**:")
        if risk.critical_count:
            parts.append(f"  - 🔴 Critical: {risk.critical_count}")
        if risk.high_count:
            parts.append(f"  - 🟠 High: {risk.high_count}")
        if risk.medium_count:
            parts.append(f"  - 🟡 Medium: {risk.medium_count}")
        if risk.low_count:
            parts.append(f"  - 🟢 Low: {risk.low_count}")
        
        # Vulnerability types
        types_found = set(f.vulnerability_type.value for f in report.findings)
        parts.append(f"\n**Vulnerability Types**: {', '.join(types_found)}")
        
        return '\n'.join(parts)


def run_sast_scan(content: str, file_path: str = "") -> str:
    """
    Tool wrapper - SAST güvenlik taraması yapar.
    
    Args:
        content: Dosya içeriği
        file_path: Dosya yolu
        
    Returns:
        Formatlanmış güvenlik raporu
    """
    analyzer = SASTAnalyzer()
    report = analyzer.analyze(content, file_path)
    
    output = [f"## 🔒 SAST Security Scan: `{file_path or 'Code'}`\n"]
    output.append(report.summary)
    
    if report.findings:
        output.append("\n### Security Findings:\n")
        
        # Önce critical ve high'ları göster
        sorted_findings = sorted(report.findings, key=lambda x: x.severity.value)
        
        for finding in sorted_findings[:15]:  # Max 15 bulgu
            severity_icon = {
                Severity.CRITICAL: "🔴",
                Severity.HIGH: "🟠",
                Severity.MEDIUM: "🟡",
                Severity.LOW: "🟢",
                Severity.INFO: "ℹ️"
            }
            
            output.append(f"#### {severity_icon.get(finding.severity, '')} Line {finding.line_number}: {finding.vulnerability_type.value}")
            output.append(f"**Severity**: {finding.severity.value} | **CWE**: {finding.cwe_id}")
            output.append(f"```\n{finding.line_content}\n```")
            output.append(f"**Issue**: {finding.description}")
            output.append(f"**Fix**: {finding.recommendation}\n")
    
    return '\n'.join(output)
