import hmac
import hashlib
import time
from typing import Dict, List, Tuple
from dataclasses import dataclass
from pathlib import Path


# =========================
# CONSTANTS
# =========================

REQUIREMENTS_FILE = "requirements.txt"
REPORT_FILE = "security_audit_report.md"

# Имитация базы уязвимостей (package -> минимально безопасная версия)
VULNERABILITY_DB: Dict[str, str] = {
    "fastapi": "0.100.0",
    "requests": "2.31.0",
    "sqlalchemy": "2.0.0",
    "pillow": "10.0.0",
}

# Хеш «пароля» для доступа к API (имитация)
API_ACCESS_HASH = hashlib.sha256(b"secure-audit-token").hexdigest()


# =========================
# DATA MODELS
# =========================

@dataclass(frozen=True)
class PackageInfo:
    name: str
    version: str


@dataclass(frozen=True)
class AuditResult:
    package: str
    installed_version: str
    safe_version: str
    vulnerable: bool


# =========================
# SECURITY UTILITIES
# =========================

def constant_time_compare(a: str, b: str) -> bool:
    """
    Безопасное сравнение строк, устойчивое к тайминговым атакам.
    """
    return hmac.compare_digest(a, b)


def authenticate(api_token: str) -> None:
    """
    Имитация аутентификации к API уязвимостей.
    Не раскрывает деталей причины отказа.
    """
    token_hash = hashlib.sha256(api_token.encode()).hexdigest()

    if not constant_time_compare(token_hash, API_ACCESS_HASH):
        # Унифицированное сообщение без раскрытия деталей
        raise PermissionError("Доступ запрещён")


# =========================
# VERSION UTILITIES
# =========================

def parse_version(version: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def is_version_vulnerable(installed: str, safe: str) -> bool:
    return parse_version(installed) < parse_version(safe)


# =========================
# REQUIREMENTS PARSER
# =========================

def parse_requirements(path: str) -> List[PackageInfo]:
    packages: List[PackageInfo] = []

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if "==" not in line:
            continue

        name, version = line.split("==", 1)
        packages.append(PackageInfo(name=name.lower(), version=version))

    return packages


# =========================
# VULNERABILITY CHECKER
# =========================

class VulnerabilityService:
    """
    Имитация внешнего API базы уязвимостей.
    """

    def __init__(self, api_token: str) -> None:
        authenticate(api_token)

    def check_package(self, package: PackageInfo) -> AuditResult:
        safe_version = VULNERABILITY_DB.get(package.name)

        if not safe_version:
            return AuditResult(
                package=package.name,
                installed_version=package.version,
                safe_version="N/A",
                vulnerable=False,
            )

        vulnerable = is_version_vulnerable(package.version, safe_version)

        return AuditResult(
            package=package.name,
            installed_version=package.version,
            safe_version=safe_version,
            vulnerable=vulnerable,
        )


# =========================
# REPORT GENERATOR
# =========================

class MarkdownReportGenerator:
    """
    Генерирует отчет аудита безопасности в формате Markdown.
    """

    def generate(self, results: List[AuditResult]) -> str:
        lines = [
            "# Security Audit Report",
            "",
            f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "| Package | Installed | Safe | Status |",
            "|--------|-----------|------|--------|",
        ]

        for result in results:
            status = "❌ Vulnerable" if result.vulnerable else "✅ OK"
            lines.append(
                f"| {result.package} | "
                f"{result.installed_version} | "
                f"{result.safe_version} | "
                f"{status} |"
            )

        return "\n".join(lines)


# =========================
# AUDIT SCRIPT
# =========================

def run_security_audit(api_token: str) -> None:
    try:
        packages = parse_requirements(REQUIREMENTS_FILE)
        service = VulnerabilityService(api_token)

        results = [
            service.check_package(pkg)
            for pkg in packages
        ]

        report = MarkdownReportGenerator().generate(results)
        Path(REPORT_FILE).write_text(report, encoding="utf-8")

        print("Security audit completed successfully.")

    except PermissionError:
        # Унифицированное сообщение — защита от перебора
        print("Ошибка выполнения аудита.")
    except Exception:
        print("Ошибка выполнения аудита.")


# =========================
# ENTRYPOINT
# =========================

if __name__ == "__main__":
    # Токен передается извне (например, через переменную окружения)
    API_TOKEN = "secure-audit-token"
    run_security_audit(API_TOKEN)
