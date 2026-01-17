import re
import json
from datetime import datetime
from typing import List, Dict, Optional
from packaging import version

class SecurityAuditor:
    """
    Инструмент для анализа зависимостей на наличие известных уязвимостей.
    """

    def __init__(self, requirements_path: str):
        self.requirements_path = requirements_path
        self.report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _mock_vulnerability_api(self, package_name: str) -> List[Dict]:
        """
        Имитация API базы данных уязвимостей (например, GitHub Advisory или OSV).
        Возвращает список известных проблем для конкретного пакета.
        """
        db = {
            "requests": [{"fixed": "2.31.0", "id": "CVE-2023-32681", "severity": "High"}],
            "django": [{"fixed": "4.2.2", "id": "CVE-2023-31047", "severity": "Medium"}],
            "flask": [{"fixed": "2.3.0", "id": "CVE-2023-30861", "severity": "Critical"}]
        }
        return db.get(package_name.lower(), [])

    def parse_requirements(self) -> List[Dict[str, str]]:
        """Парсит файл requirements.txt, извлекая имя пакета и версию."""
        packages = []
        try:
            with open(self.requirements_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # Регулярное выражение для захвата 'package==version'
                    match = re.match(r"^([a-zA-Z0-9\-_]+)==([a-zA-Z0-9\.]+)", line)
                    if match:
                        packages.append({"name": match.group(1), "version": match.group(2)})
        except FileNotFoundError:
            print(f"Ошибка: Файл {self.requirements_path} не найден.")
        return packages

    def run_audit(self) -> str:
        """Основной цикл аудита и генерация Markdown-отчета."""
        packages = self.parse_requirements()
        vulnerabilities_found = []
        
        for pkg in packages:
            issues = self._mock_vulnerability_api(pkg["name"])
            for issue in issues:
                # Сравнение версий: если установленная версия меньше исправленной
                if version.parse(pkg["version"]) < version.parse(issue["fixed"]):
                    vulnerabilities_found.append({
                        "package": pkg["name"],
                        "installed": pkg["version"],
                        "fixed_in": issue["fixed"],
                        "id": issue["id"],
                        "severity": issue["severity"]
                    })

        return self._generate_markdown(vulnerabilities_found)

    def _generate_markdown(self, issues: List[Dict]) -> str:
        """Формирует итоговый отчет в формате Markdown."""
        report = [
            f"# Отчет по аудиту безопасности зависимостей",
            f"**Дата проверки:** {self.report_date}",
            f"**Статус:** {'УЯЗВИМОСТИ НАЙДЕНЫ' if issues else 'БЕЗОПАСНО'}\n",
            "| Пакет | Версия | Исправлено в | ID | Уровень |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ]

        if not issues:
            report.append("| - | - | - | - | - |")
        else:
            for issue in issues:
                report.append(
                    f"| **{issue['package']}** | {issue['installed']} | "
                    f"{issue['fixed_in']} | {issue['id']} | `{issue['severity']}` |"
                )

        report.append(f"\n*Всего найдено угроз: {len(issues)}*")
        return "\n".join(report)

# --- Запуск инструмента ---

if __name__ == "__main__":
    # Создаем фиктивный файл для демонстрации
    with open("requirements.txt", "w") as f:
        f.write("requests==2.28.1\nflask==2.1.0\nnumpy==1.24.0\ndjango==3.2.0")

    auditor = SecurityAuditor("requirements.txt")
    markdown_report = auditor.run_audit()

    print(markdown_report)

    # Сохранение в файл
    with open("SECURITY_AUDIT.md", "w") as f:
        f.write(markdown_report)