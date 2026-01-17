import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


# =========================
# Доменные модели
# =========================

class VulnerabilitySeverity(str, Enum):
    """
    Уровни критичности уязвимостей.
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class Dependency:
    """
    Зависимость из requirements.txt.
    """
    name: str
    version: str


@dataclass(frozen=True)
class VulnerabilityReport:
    """
    Результат проверки одной зависимости.
    """
    dependency: Dependency
    vulnerable: bool
    severity: Optional[VulnerabilitySeverity]
    description: Optional[str]


# =========================
# Парсер requirements.txt
# =========================

class RequirementsParser:
    """
    Парсер файла requirements.txt.
    """

    _pattern = re.compile(r"^([a-zA-Z0-9_\-]+)==([\w\.]+)$")

    def parse(self, path: Path) -> List[Dependency]:
        if not path.exists():
            raise FileNotFoundError(f"{path} not found")

        dependencies: List[Dependency] = []

        for line in path.read_text().splitlines():
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            match = self._pattern.match(line)
            if not match:
                continue

            name, version = match.groups()
            dependencies.append(Dependency(name, version))

        return dependencies


# =========================
# Имитация API уязвимостей
# =========================

class VulnerabilityApiClient:
    """
    Имитация внешнего API базы уязвимостей.
    """

    _fake_database: Dict[str, Dict[str, VulnerabilitySeverity]] = {
        "requests": {
            "2.19.0": VulnerabilitySeverity.HIGH,
            "2.20.0": VulnerabilitySeverity.MEDIUM,
        },
        "flask": {
            "1.0": VulnerabilitySeverity.HIGH,
        },
        "django": {
            "2.2": VulnerabilitySeverity.MEDIUM,
        },
    }

    def check(self, dependency: Dependency) -> VulnerabilityReport:
        vulnerable_versions = self._fake_database.get(dependency.name)

        if not vulnerable_versions:
            return VulnerabilityReport(
                dependency=dependency,
                vulnerable=False,
                severity=None,
                description=None,
            )

        severity = vulnerable_versions.get(dependency.version)
        if not severity:
            return VulnerabilityReport(
                dependency=dependency,
                vulnerable=False,
                severity=None,
                description=None,
            )

        return VulnerabilityReport(
            dependency=dependency,
            vulnerable=True,
            severity=severity,
            description=(
                f"Known vulnerability in {dependency.name} "
                f"version {dependency.version}"
            ),
        )


# =========================
# Генератор Markdown-отчёта
# =========================

class MarkdownReportBuilder:
    """
    Генерирует Markdown-отчёт аудита безопасности.
    """

    def build(self, reports: List[VulnerabilityReport]) -> str:
        lines: List[str] = [
            "# 🔐 Dependency Security Audit Report",
            "",
            "| Package | Version | Vulnerable | Severity | Description |",
            "|--------|---------|------------|----------|-------------|",
        ]

        for report in reports:
            lines.append(self._format_row(report))

        lines.extend(self._summary(reports))
        return "\n".join(lines)

    def _format_row(self, report: VulnerabilityReport) -> str:
        return (
            f"| {report.dependency.name} "
            f"| {report.dependency.version} "
            f"| {'YES' if report.vulnerable else 'NO'} "
            f"| {report.severity or '-'} "
            f"| {report.description or '-'} |"
        )

    def _summary(self, reports: List[VulnerabilityReport]) -> List[str]:
        total = len(reports)
        vulnerable = sum(1 for r in reports if r.vulnerable)

        return [
            "",
            "## 📊 Summary",
            "",
            f"- Total dependencies: **{total}**",
            f"- Vulnerable dependencies: **{vulnerable}**",
        ]


# =========================
# Основной сервис аудита
# =========================

class SecurityAuditService:
    """
    Оркестратор аудита безопасности.
    """

    def __init__(
        self,
        parser: RequirementsParser,
        api_client: VulnerabilityApiClient,
        report_builder: MarkdownReportBuilder,
    ) -> None:
        self._parser = parser
        self._api_client = api_client
        self._report_builder = report_builder

    def run(self, requirements_path: Path) -> str:
        dependencies = self._parser.parse(requirements_path)

        reports = [
            self._api_client.check(dep)
            for dep in dependencies
        ]

        return self._report_builder.build(reports)


# =========================
# Точка входа
# =========================

if __name__ == "__main__":
    service = SecurityAuditService(
        parser=RequirementsParser(),
        api_client=VulnerabilityApiClient(),
        report_builder=MarkdownReportBuilder(),
    )

    report = service.run(Path("requirements.txt"))
    Path("security_audit_report.md").write_text(report)

    print("Security audit completed. Report saved to security_audit_report.md")
