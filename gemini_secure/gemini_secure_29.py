import re
import json
from typing import List, Dict, Final

class DependencyAuditor:
    """Сервис для анализа уязвимостей в зависимостях проекта."""
    
    # Регулярное выражение для безопасного парсинга (библиотека==версия)
    PACKAGE_RE: Final[re.Pattern] = re.compile(r"^([a-zA-Z0-9_\-\[\]]+)==([a-zA-Z0-9\.\-]+)$")

    def __init__(self):
        # Имитация базы данных уязвимостей
        self._vulnerability_db = {
            "requests": {"vulnerable_before": "2.31.0", "cve": "CVE-2023-32681", "severity": "High"},
            "django": {"vulnerable_before": "4.2.0", "cve": "CVE-2023-31047", "severity": "Critical"},
            "flask": {"vulnerable_before": "2.2.5", "cve": "CVE-2023-30861", "severity": "Medium"}
        }

    def parse_requirements(self, file_path: str) -> List[Dict[str, str]]:
        dependencies = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    
                    match = self.PACKAGE_RE.match(line)
                    if match:
                        dependencies.append({"name": match.group(1), "version": match.group(2)})
        except FileNotFoundError:
            return []
        return dependencies

    def generate_report(self, requirements_path: str, output_path: str):
        deps = self.parse_requirements(requirements_path)
        report_lines = ["# Security Audit Report\n", "| Package | Version | Status | Severity | CVE |", "|---|---|---|---|---|"]
        
        for dep in deps:
            name, version = dep['name'].lower(), dep['version']
            vuln = self._vulnerability_db.get(name)
            
            if vuln and version < vuln["vulnerable_before"]:
                status = "❌ Vulnerable"
                cve = vuln["cve"]
                severity = vuln["severity"]
            else:
                status = "✅ Secure"
                cve = "N/A"
                severity = "N/A"
            
            report_lines.append(f"| {name} | {version} | {status} | {severity} | {cve} |")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))

# Использование: 
# auditor = DependencyAuditor()
# auditor.generate_report("requirements.txt", "audit_report.md")