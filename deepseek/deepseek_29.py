import re
import requests
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import argparse
from pathlib import Path


@dataclass
class Vulnerability:
    """Информация об уязвимости."""
    cve_id: str
    severity: str
    description: str
    affected_versions: str
    fixed_versions: List[str]
    published_date: str
    cvss_score: Optional[float] = None


@dataclass
class PackageInfo:
    """Информация о пакете."""
    name: str
    current_version: str
    latest_version: str
    vulnerabilities: List[Vulnerability]
    has_vulnerabilities: bool
    needs_update: bool


class SecurityAuditor:
    """Класс для аудита безопасности зависимостей Python."""
    
    # Регулярное выражение для парсинга requirements.txt
    REQUIREMENTS_PATTERN = r'^([a-zA-Z0-9_.-]+)([><=!~]=?)?([\d\w\.-]+)?$'
    
    # API endpoint для проверки уязвимостей (имитация)
    VULN_API_BASE = "https://api.security-audit.mock"
    
    # Уровни серьезности уязвимостей
    SEVERITY_LEVELS = {
        'CRITICAL': 4,
        'HIGH': 3,
        'MEDIUM': 2,
        'LOW': 1
    }
    
    def __init__(self, requirements_path: str = "requirements.txt"):
        """
        Инициализация аудитора безопасности.
        
        Args:
            requirements_path: Путь к файлу requirements.txt
        """
        self.requirements_path = Path(requirements_path)
        self.packages: Dict[str, PackageInfo] = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'SecurityAuditor/1.0',
            'Accept': 'application/json'
        })
    
    def parse_requirements(self) -> Dict[str, str]:
        """
        Парсит файл requirements.txt.
        
        Returns:
            Словарь {имя_пакета: версия}
        """
        packages = {}
        
        if not self.requirements_path.exists():
            raise FileNotFoundError(f"Файл {self.requirements_path} не найден")
        
        with open(self.requirements_path, 'r', encoding='utf-8') as f:
            for line_number, line in enumerate(f, 1):
                line = line.strip()
                
                # Пропускаем комментарии и пустые строки
                if not line or line.startswith('#'):
                    continue
                
                # Убираем лишние пробелы
                line = re.sub(r'\s+', '', line)
                
                # Парсим имя пакета и версию
                match = re.match(self.REQUIREMENTS_PATTERN, line)
                if match:
                    name = match.group(1)
                    version = match.group(3) if match.group(3) else 'latest'
                    
                    # Нормализуем имя пакета (pip принимает разные форматы)
                    name = name.lower().replace('_', '-')
                    packages[name] = version
                else:
                    print(f"Предупреждение: строка {line_number} не может быть распознана: {line}")
        
        return packages
    
    def check_package_vulnerabilities(self, package_name: str, 
                                     version: str) -> List[Vulnerability]:
        """
        Проверяет уязвимости пакета через API (имитация).
        
        Args:
            package_name: Имя пакета
            version: Текущая версия пакета
        
        Returns:
            Список уязвимостей
        """
        # В реальном приложении здесь был бы вызов реального API
        # Например: PyPI Security, NVD, Snyk, etc.
        
        # Имитация ответа API
        mock_vulnerabilities = []
        
        # Примеры уязвимостей для популярных пакетов
        mock_data = {
            'django': [
                Vulnerability(
                    cve_id="CVE-2023-46695",
                    severity="HIGH",
                    description="Cross-site scripting (XSS) vulnerability in Django admin",
                    affected_versions="<4.2.8",
                    fixed_versions=["4.2.8", "5.0.2"],
                    published_date="2023-12-05",
                    cvss_score=7.5
                )
            ],
            'requests': [
                Vulnerability(
                    cve_id="CVE-2023-32681",
                    severity="MEDIUM",
                    description="Information disclosure via redirect",
                    affected_versions="<2.31.0",
                    fixed_versions=["2.31.0"],
                    published_date="2023-06-26",
                    cvss_score=5.3
                )
            ],
            'cryptography': [
                Vulnerability(
                    cve_id="CVE-2023-49083",
                    severity="CRITICAL",
                    description="Buffer overflow in RSA key parsing",
                    affected_versions="<41.0.7",
                    fixed_versions=["41.0.7"],
                    published_date="2023-11-30",
                    cvss_score=9.8
                )
            ]
        }
        
        # Возвращаем моковые данные если пакет есть в списке
        if package_name.lower() in mock_data:
            return mock_data[package_name.lower()]
        
        return mock_vulnerabilities
    
    def get_latest_version(self, package_name: str) -> str:
        """
        Получает последнюю версию пакета (имитация).
        
        Args:
            package_name: Имя пакета
        
        Returns:
            Последняя версия пакета
        """
        # В реальном приложении здесь был бы запрос к PyPI API
        mock_versions = {
            'django': '5.0.1',
            'requests': '2.31.0',
            'flask': '3.0.0',
            'numpy': '1.26.2',
            'pandas': '2.1.4',
            'cryptography': '42.0.0'
        }
        
        return mock_versions.get(package_name.lower(), 'unknown')
    
    def audit(self) -> None:
        """Выполняет полный аудит зависимостей."""
        print(f"🔍 Начинаем аудит безопасности для {self.requirements_path}")
        
        try:
            # Парсим зависимости
            dependencies = self.parse_requirements()
            print(f"📦 Найдено {len(dependencies)} пакетов для проверки")
            
            # Проверяем каждый пакет
            for package_name, current_version in dependencies.items():
                print(f"  Проверяем {package_name}=={current_version}...")
                
                # Получаем информацию об уязвимостях
                vulnerabilities = self.check_package_vulnerabilities(
                    package_name, 
                    current_version
                )
                
                # Получаем последнюю версию
                latest_version = self.get_latest_version(package_name)
                
                # Определяем, нуждается ли пакет в обновлении
                needs_update = latest_version != 'unknown' and current_version != latest_version
                
                # Сохраняем информацию о пакете
                self.packages[package_name] = PackageInfo(
                    name=package_name,
                    current_version=current_version,
                    latest_version=latest_version,
                    vulnerabilities=vulnerabilities,
                    has_vulnerabilities=bool(vulnerabilities),
                    needs_update=needs_update
                )
            
            print("✅ Аудит завершен")
            
        except Exception as e:
            print(f"❌ Ошибка при выполнении аудита: {e}")
            raise
    
    def generate_markdown_report(self, output_path: str = "security_audit.md") -> str:
        """
        Генерирует отчет в формате Markdown.
        
        Args:
            output_path: Путь для сохранения отчета
        
        Returns:
            Содержимое отчета
        """
        report_lines = []
        
        # Заголовок отчета
        report_lines.append(f"# 📋 Отчет аудита безопасности зависимостей")
        report_lines.append(f"\n**Дата генерации:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**Файл зависимостей:** {self.requirements_path}")
        report_lines.append(f"**Всего пакетов:** {len(self.packages)}")
        
        # Статистика
        vulnerable_count = sum(1 for p in self.packages.values() if p.has_vulnerabilities)
        outdated_count = sum(1 for p in self.packages.values() if p.needs_update)
        
        report_lines.append(f"**Пакетов с уязвимостями:** {vulnerable_count}")
        report_lines.append(f"**Устаревших пакетов:** {outdated_count}")
        
        # Сводка
        report_lines.append("\n## 📊 Сводка")
        
        if vulnerable_count == 0 and outdated_count == 0:
            report_lines.append("✅ Все пакеты безопасны и актуальны!")
        else:
            if vulnerable_count > 0:
                report_lines.append(f"⚠️  **Найдено пакетов с уязвимостями: {vulnerable_count}**")
            if outdated_count > 0:
                report_lines.append(f"📅 **Устаревших пакетов: {outdated_count}**")
        
        # Детальная информация по пакетам
        report_lines.append("\n## 📦 Детальная информация по пакетам")
        
        for package_name, package_info in self.packages.items():
            report_lines.append(f"\n### {package_name}")
            report_lines.append(f"- **Текущая версия:** {package_info.current_version}")
            report_lines.append(f"- **Последняя версия:** {package_info.latest_version}")
            
            # Статус обновления
            if package_info.needs_update:
                report_lines.append(f"- **Статус:** ⚠️ Требуется обновление до {package_info.latest_version}")
            else:
                report_lines.append(f"- **Статус:** ✅ Актуальная версия")
            
            # Уязвимости
            if package_info.has_vulnerabilities:
                report_lines.append(f"- **Безопасность:** ❌ Найдены уязвимости")
                for vuln in package_info.vulnerabilities:
                    report_lines.append(f"  #### {vuln.cve_id} ({vuln.severity})")
                    report_lines.append(f"  **Описание:** {vuln.description}")
                    report_lines.append(f"  **Затронутые версии:** {vuln.affected_versions}")
                    report_lines.append(f"  **Исправлено в:** {', '.join(vuln.fixed_versions)}")
                    if vuln.cvss_score:
                        report_lines.append(f"  **CVSS Score:** {vuln.cvss_score}/10")
                    report_lines.append(f"  **Дата публикации:** {vuln.published_date}")
            else:
                report_lines.append(f"- **Безопасность:** ✅ Уязвимостей не обнаружено")
        
        # Рекомендации
        report_lines.append("\n## 🚀 Рекомендации")
        
        vulnerable_packages = [p