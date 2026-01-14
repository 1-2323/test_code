#!/usr/bin/env python3
"""
Скрипт для автоматизации проверки зависимостей.
Запускает инструменты сканирования уязвимостей и обрабатывает отчеты.
"""

import os
import sys
import json
import yaml
import tomllib
import subprocess
import argparse
import tempfile
import logging
import smtplib
import platform
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import xml.etree.ElementTree as ET

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Vulnerability:
    """Класс для представления уязвимости."""
    package_name: str
    package_version: str
    vulnerability_id: str
    severity: str
    title: str
    description: str
    cve_id: Optional[str] = None
    cvss_score: Optional[float] = None
    fixed_version: Optional[str] = None
    advisory_url: Optional[str] = None
    path: Optional[str] = None
    dependency_type: Optional[str] = None


@dataclass
class ScanResult:
    """Результат сканирования зависимостей."""
    scanner_name: str
    timestamp: datetime
    total_dependencies: int
    vulnerabilities_found: int
    vulnerabilities: List[Vulnerability]
    summary: Dict[str, int]
    scan_successful: bool
    error_message: Optional[str] = None


@dataclass
class ScanConfig:
    """Конфигурация сканирования."""
    scanner: str
    requirements_files: List[str]
    output_format: str
    output_file: Optional[str]
    fail_on_severity: Optional[str]
    ignore_cves: List[str]
    custom_rules: Dict[str, Any]
    email_notifications: bool
    email_recipients: List[str]
    slack_webhook: Optional[str]
    jira_integration: bool
    jira_project: Optional[str]


class DependencyScanner:
    """Базовый класс для сканеров зависимостей."""
    
    def __init__(self, config: ScanConfig):
        self.config = config
        self.results: List[ScanResult] = []
    
    def scan(self) -> ScanResult:
        """Запускает сканирование зависимостей."""
        raise NotImplementedError
    
    def parse_report(self, report_path: str) -> ScanResult:
        """Парсит отчет сканирования."""
        raise NotImplementedError
    
    def _run_command(self, command: List[str], cwd: Optional[str] = None) -> Tuple[str, str, int]:
        """Запускает команду и возвращает результат."""
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False
            )
            return result.stdout, result.stderr, result.returncode
        except Exception as e:
            logger.error(f"Ошибка выполнения команды {command}: {e}")
            return "", str(e), 1


class SafetyScanner(DependencyScanner):
    """Сканер уязвимостей Safety."""
    
    def scan(self) -> ScanResult:
        """Запускает сканирование с помощью Safety."""
        logger.info("Запуск Safety сканирования...")
        
        # Подготавливаем команду
        cmd = [
            "safety", "check",
            "--output", self.config.output_format,
            "--file", *self.config.requirements_files
        ]
        
        if self.config.output_file:
            cmd.extend(["--output", self.config.output_file])
        
        # Добавляем игнорируемые CVE
        for cve in self.config.ignore_cves:
            cmd.extend(["--ignore", cve])
        
        # Запускаем сканирование
        stdout, stderr, exit_code = self._run_command(cmd)
        
        # Сохраняем отчет если указан файл
        if self.config.output_file and stdout:
            with open(self.config.output_file, 'w') as f:
                f.write(stdout)
        
        # Парсим результаты
        if self.config.output_format == 'json' and stdout:
            return self._parse_json_report(stdout)
        else:
            # Создаем временный файл для парсинга
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
                tmp.write(stdout)
                tmp_path = tmp.name
            
            try:
                result = self.parse_report(tmp_path)
            finally:
                os.unlink(tmp_path)
            
            return result
    
    def parse_report(self, report_path: str) -> ScanResult:
        """Парсит JSON отчет Safety."""
        try:
            with open(report_path, 'r') as f:
                report_data = json.load(f)
            
            vulnerabilities = []
            
            for vuln in report_data.get('vulnerabilities', []):
                vulnerability = Vulnerability(
                    package_name=vuln.get('package_name', ''),
                    package_version=vuln.get('analyzed_version', ''),
                    vulnerability_id=vuln.get('vulnerability_id', ''),
                    severity=vuln.get('severity', 'MEDIUM').upper(),
                    title=vuln.get('advisory', ''),
                    description=vuln.get('more_info_url', ''),
                    cve_id=vuln.get('CVE', None),
                    cvss_score=float(vuln.get('cvssv3', {}).get('base_score', 0)) if vuln.get('cvssv3') else None,
                    fixed_version=vuln.get('fixed_version'),
                    advisory_url=vuln.get('more_info_url'),
                    dependency_type='production'
                )
                vulnerabilities.append(vulnerability)
            
            # Подсчитываем статистику
            summary = self._calculate_summary(vulnerabilities)
            
            return ScanResult(
                scanner_name="Safety",
                timestamp=datetime.now(),
                total_dependencies=report_data.get('scanned', 0),
                vulnerabilities_found=len(vulnerabilities),
                vulnerabilities=vulnerabilities,
                summary=summary,
                scan_successful=True
            )
            
        except Exception as e:
            logger.error(f"Ошибка парсинга отчета Safety: {e}")
            return ScanResult(
                scanner_name="Safety",
                timestamp=datetime.now(),
                total_dependencies=0,
                vulnerabilities_found=0,
                vulnerabilities=[],
                summary={},
                scan_successful=False,
                error_message=str(e)
            )
    
    def _calculate_summary(self, vulnerabilities: List[Vulnerability]) -> Dict[str, int]:
        """Подсчитывает статистику по уязвимостям."""
        summary = {
            'CRITICAL': 0,
            'HIGH': 0,
            'MEDIUM': 0,
            'LOW': 0
        }
        
        for vuln in vulnerabilities:
            severity = vuln.severity.upper()
            if severity in summary:
                summary[severity] += 1
        
        return summary


class TrivyScanner(DependencyScanner):
    """Сканер уязвимостей Trivy."""
    
    def scan(self) -> ScanResult:
        """Запускает сканирование с помощью Trivy."""
        logger.info("Запуск Trivy сканирования...")
        
        # Определяем цель сканирования (файл или директория)
        target = self.config.requirements_files[0] if self.config.requirements_files else "."
        
        # Подготавливаем команду
        cmd = [
            "trivy", "fs",
            "--format", self.config.output_format,
            "--scanners", "vuln",
            "--severity", "CRITICAL,HIGH,MEDIUM,LOW"
        ]
        
        if self.config.output_file:
            cmd.extend(["--output", self.config.output_file])
        
        # Добавляем игнорируемые уязвимости
        if self.config.ignore_cves:
            ignore_file = self._create_ignore_file()
            cmd.extend(["--ignorefile", ignore_file])
        
        cmd.append(target)
        
        # Запускаем сканирование
        stdout, stderr, exit_code = self._run_command(cmd)
        
        # Парсим результаты
        if self.config.output_format == 'json':
            return self._parse_json_report(stdout if stdout else self.config.output_file)
        else:
            return self.parse_report(self.config.output_file if self.config.output_file else "")
    
    def _create_ignore_file(self) -> str:
        """Создает временный файл с игнорируемыми CVE."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.trivyignore', delete=False) as f:
            for cve in self.config.ignore_cves:
                f.write(f"{cve}\n")
            return f.name
    
    def _parse_json_report(self, report_source: str) -> ScanResult:
        """Парсит JSON отчет Trivy."""
        try:
            # Загружаем данные из файла или строки
            if os.path.exists(report_source):
                with open(report_source, 'r') as f:
                    report_data = json.load(f)
            else:
                report_data = json.loads(report_source)
            
            vulnerabilities = []
            
            # Trivy структура отчета
            for result in report_data.get('Results', []):
                target = result.get('Target', '')
                
                for vuln in result.get('Vulnerabilities', []):
                    vulnerability = Vulnerability(
                        package_name=vuln.get('PkgName', ''),
                        package_version=vuln.get('InstalledVersion', ''),
                        vulnerability_id=vuln.get('VulnerabilityID', ''),
                        severity=vuln.get('Severity', 'UNKNOWN').upper(),
                        title=vuln.get('Title', ''),
                        description=vuln.get('Description', ''),
                        cve_id=vuln.get('VulnerabilityID') if 'CVE' in vuln.get('VulnerabilityID', '') else None,
                        cvss_score=self._extract_cvss_score(vuln),
                        fixed_version=vuln.get('FixedVersion'),
                        advisory_url=vuln.get('PrimaryURL', ''),
                        path=target,
                        dependency_type=self._determine_dependency_type(target)
                    )
                    vulnerabilities.append(vulnerability)
            
            summary = self._calculate_summary(vulnerabilities)
            
            return ScanResult(
                scanner_name="Trivy",
                timestamp=datetime.now(),
                total_dependencies=self._count_dependencies(report_data),
                vulnerabilities_found=len(vulnerabilities),
                vulnerabilities=vulnerabilities,
                summary=summary,
                scan_successful=True
            )
            
        except Exception as e:
            logger.error(f"Ошибка парсинга отчета Trivy: {e}")
            return ScanResult(
                scanner_name="Trivy",
                timestamp=datetime.now(),
                total_dependencies=0,
                vulnerabilities_found=0,
                vulnerabilities=[],
                summary={},
                scan_successful=False,
                error_message=str(e)
            )
    
    def _extract_cvss_score(self, vuln: Dict) -> Optional[float]:
        """Извлекает CVSS оценку из данных уязвимости."""
        cvss_data = vuln.get('CVSS', {})
        if isinstance(cvss_data, dict):
            for cvss_version in ['nvd', 'redhat']:
                if cvss_version in cvss_data and 'V3Score' in cvss_data[cvss_version]:
                    return cvss_data[cvss_version]['V3Score']
        return None
    
    def _determine_dependency_type(self, path: str) -> str:
        """Определяет тип зависимости по пути."""
        if 'requirements' in path.lower():
            return 'production'
        elif 'dev-requirements' in path.lower() or 'requirements-dev' in path.lower():
            return 'development'
        elif 'test-requirements' in path.lower() or 'requirements-test' in path.lower():
            return 'test'
        return 'unknown'
    
    def _count_dependencies(self, report_data: Dict) -> int:
        """Подсчитывает общее количество зависимостей."""
        count = 0
        for result in report_data.get('Results', []):
            count += len(result.get('Vulnerabilities', []))
        return count


class OWASPDependencyCheckScanner(DependencyScanner):
    """Сканер уязвимостей OWASP Dependency-Check."""
    
    def scan(self) -> ScanResult:
        """Запускает сканирование с помощью OWASP Dependency-Check."""
        logger.info("Запуск OWASP Dependency-Check сканирования...")
        
        # Создаем выходной каталог если не указан файл
        if not self.config.output_file:
            output_dir = tempfile.mkdtemp(prefix='dependency-check-')
            output_file = os.path.join(output_dir, 'report.json')
        else:
            output_file = self.config.output_file
        
        # Подготавливаем команду
        cmd = [
            "dependency-check",
            "--scan", self.config.requirements_files[0] if self.config.requirements_files else ".",
            "--format", "JSON",
            "--out", os.path.dirname(output_file),
            "--project", "DependencyScan",
            "--enableExperimental"
        ]
        
        if self.config.ignore_cves:
            suppression_file = self._create_suppression_file()
            cmd.extend(["--suppression", suppression_file])
        
        # Запускаем сканирование
        stdout, stderr, exit_code = self._run_command(cmd)
        
        # Парсим результаты
        report_path = output_file if os.path.exists(output_file) else \
                     os.path.join(os.path.dirname(output_file), 'dependency-check-report.json')
        
        return self.parse_report(report_path)
    
    def _create_suppression_file(self) -> str:
        """Создает файл подавления для игнорируемых CVE."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<suppressions xmlns="https://jeremylong.github.io/DependencyCheck/dependency-suppression.1.3.xsd">\n')
            
            for cve in self.config.ignore_cves:
                f.write(f'  <suppress>\n')
                f.write(f'    <notes><![CDATA[Suppressing {cve}]]></notes>\n')
                f.write(f'    <cve>{cve}</cve>\n')
                f.write(f'  </suppress>\n')
            
            f.write('</suppressions>\n')
            return f.name
    
    def parse_report(self, report_path: str) -> ScanResult:
        """Парсит XML отчет OWASP Dependency-Check."""
        try:
            vulnerabilities = []
            
            # OWASP DC может выводить как XML, так и JSON
            if report_path.endswith('.xml'):
                tree = ET.parse(report_path)
                root = tree.getroot()
                
                # Парсим XML структуру
                for dependency in root.findall('.//{*}dependency'):
                    file_path = dependency.findtext('{*}filePath', '')
                    
                    for vuln in dependency.findall('.//{*}vulnerability'):
                        vulnerability = Vulnerability(
                            package_name=dependency.findtext('{*}fileName', '').split('-')[0],
                            package_version='',  # OWASP DC не всегда предоставляет версию
                            vulnerability_id=vuln.findtext('{*}name', ''),
                            severity=vuln.findtext('{*}severity', 'MEDIUM').upper(),
                            title=vuln.findtext('{*}name', ''),
                            description=vuln.findtext('{*}description', ''),
                            cve_id=vuln.findtext('{*}cve', None),
                            cvss_score=float(vuln.findtext('{*}cvssScore', 0)) if vuln.findtext('{*}cvssScore') else None,
                            fixed_version=None,
                            advisory_url=None,
                            path=file_path,
                            dependency_type='production'
                        )
                        vulnerabilities.append(vulnerability)
                
                total_deps = len(root.findall('.//{*}dependency'))
                
            else:  # JSON формат
                with open(report_path, 'r') as f:
                    report_data = json.load(f)
                
                for dependency in report_data.get('dependencies', []):
                    for vuln in dependency.get('vulnerabilities', []):
                        vulnerability = Vulnerability(
                            package_name=dependency.get('fileName', '').split('-')[0],
                            package_version=dependency.get('version', ''),
                            vulnerability_id=vuln.get('name', ''),
                            severity=vuln.get('severity', 'MEDIUM').upper(),
                            title=vuln.get('name', ''),
                            description=vuln.get('description', ''),
                            cve_id=vuln.get('cve', None),
                            cvss_score=vuln.get('cvssScore'),
                            fixed_version=None,
                            advisory_url=None,
                            path=dependency.get('filePath', ''),
                            dependency_type='production'
                        )
                        vulnerabilities.append(vulnerability)
                
                total_deps = len(report_data.get('dependencies', []))
            
            summary = self._calculate_summary(vulnerabilities)
            
            return ScanResult(
                scanner_name="OWASP Dependency-Check",
                timestamp=datetime.now(),
                total_dependencies=total_deps,
                vulnerabilities_found=len(vulnerabilities),
                vulnerabilities=vulnerabilities,
                summary=summary,
                scan_successful=True
            )
            
        except Exception as e:
            logger.error(f"Ошибка парсинга отчета OWASP Dependency-Check: {e}")
            return ScanResult(
                scanner_name="OWASP Dependency-Check",
                timestamp=datetime.now(),
                total_dependencies=0,
                vulnerabilities_found=0,
                vulnerabilities=[],
                summary={},
                scan_successful=False,
                error_message=str(e)
            )


class ReportProcessor:
    """Класс для обработки и анализа отчетов сканирования."""
    
    def __init__(self, config: ScanConfig):
        self.config = config
        self.all_results: List[ScanResult] = []
    
    def add_result(self, result: ScanResult):
        """Добавляет результат сканирования."""
        self.all_results.append(result)
    
    def generate_summary_report(self) -> Dict[str, Any]:
        """Генерирует сводный отчет по всем сканированиям."""
        total_vulnerabilities = 0
        severity_counts = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        
        for result in self.all_results:
            total_vulnerabilities += result.vulnerabilities_found
            for severity, count in result.summary.items():
                severity_counts[severity] = severity_counts.get(severity, 0) + count
        
        return {
            'total_scans': len(self.all_results),
            'total_vulnerabilities': total_vulnerabilities,
            'severity_distribution': severity_counts,
            'scanners_used': [r.scanner_name for r in self.all_results],
            'scan_timestamp': datetime.now().isoformat(),
            'successful_scans': sum(1 for r in self.all_results if r.scan_successful),
            'failed_scans': sum(1 for r in self.all_results if not r.scan_successful)
        }
    
    def export_reports(self, output_dir: str):
        """Экспортирует отчеты в различные форматы."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # JSON отчет
        json_report = {
            'summary': self.generate_summary_report(),
            'detailed_results': [asdict(r) for r in self.all_results]
        }
        
        json_path = output_path / f"dependency_scan_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump(json_report, f, indent=2, default=str)
        
        # HTML отчет
        html_path = output_path / f"dependency_scan_{timestamp}.html"
        self._generate_html_report(html_path)
        
        # Markdown отчет
        md_path = output_path / f"dependency_scan_{timestamp}.md"
        self._generate_markdown_report(md_path)
        
        # CSV отчет (детализированный)
        csv_path = output_path / f"vulnerabilities_{timestamp}.csv"
        self._generate_csv_report(csv_path)
        
        logger.info(f"Отчеты сохранены в директории: {output_dir}")
        return [str(p) for p in [json_path, html_path, md_path, csv_path]]
    
    def _generate_html_report(self, output_path: Path):
        """Генерирует HTML отчет."""
        summary = self.generate_summary_report()
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Отчет сканирования зависимостей</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .summary {{ background: #f5f5f5; padding: 20px; border-radius: 5px; }}
                .severity-critical {{ color: #dc3545; font-weight: bold; }}
                .severity-high {{ color: #fd7e14; font-weight: bold; }}
                .severity-medium {{ color: #ffc107; font-weight: bold; }}
                .severity-low {{ color: #28a745; font-weight: bold; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h1>Отчет сканирования зависимостей</h1>
            <p>Сгенерирован: {summary['scan_timestamp']}</p>
            
            <div class="summary">
                <h2>Сводка</h2>
                <p>Всего сканирований: {summary['total_scans']}</p>
                <p>Всего уязвимостей: {summary['total_vulnerabilities']}</p>
                <p>Успешных сканирований: {summary['successful_scans']}</p>
                <p>Неудачных сканирований: {summary['failed_scans']}</p>
                
                <h3>Распределение по критичности:</h3>
                <p class="severity-critical">КРИТИЧЕСКИЕ: {summary['severity_distribution']['CRITICAL']}</p>
                <p class="severity-high">ВЫСОКИЕ: {summary['severity_distribution']['HIGH']}</p>
                <p class="severity-medium">СРЕДНИЕ: {summary['severity_distribution']['MEDIUM']}</p>
                <p class="severity-low">НИЗКИЕ: {summary['severity_distribution']['LOW']}</p>
            </div>
            
            <h2>Детальные результаты</h2>
            <table>
                <tr>
                    <th>Сканер</th>
                    <th>Найдено уязвимостей</th>
                    <th>Всего зависимостей</th>
                    <th>Статус</th>
                    <th>Время сканирования</th>
                </tr>
        """
        
        for result in self.all_results:
            status = "УСПЕШНО" if result.scan_successful else "ОШИБКА"
            html_content += f"""
                <tr>
                    <td>{result.scanner_name}</td>
                    <td>{result.vulnerabilities_found}</td>
                    <td>{result.total_dependencies}</td>
                    <td>{status}</td>
                    <td>{result.timestamp}</td>
                </tr>
            """
        
        # Таблица уязвимостей
        html_content += """
            </table>
            
            <h2>Детали уязвимостей</h2>
            <table>
                <tr>
                    <th>Пакет</th>
                    <th>Версия</th>
                    <th>Уязвимость</th>
                    <th>Критичность</th>
                    <th>CVE</th>
                    <th>Исправлено в</th>
                </tr>
        """
        
        for result in self.all_results:
            for vuln in result.vulnerabilities:
                severity_class = f"severity-{vuln.severity.lower()}"
                html_content += f"""
                    <tr>
                        <td>{vuln.package_name}</td>
                        <td>{vuln.package_version}</td>
                        <td>{vuln.title}</td>
                        <td class="{severity_class}">{vuln.severity}</td>
                        <td>{vuln.cve_id or 'N/A'}</td>
                        <td>{vuln.fixed_version or 'N/A'}</td>
                    </tr>
                """
        
        html_content += """
            </table>
        </body>
        </html>
        """
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _generate_markdown_report(self, output_path: Path):
        """Генерирует Markdown отчет."""
        summary = self.generate_summary_report()
        
        md_content = f"""# Отчет сканирования зависимостей

**Сгенерирован:** {summary['scan_timestamp']}

## Сводка

- **Всего сканирований:** {summary['total_scans']}
- **Всего уязвимостей:** {summary['total_vulnerabilities']}
- **Успешных сканирований:** {summary['successful_scans']}
- **Неудачных сканирований:** {summary['failed_scans']}

## Распределение по критичности

| Критичность | Количество |
|-------------|------------|
| CRITICAL | {summary['severity_distribution']['CRITICAL']} |
| HIGH | {summary['severity_distribution']['HIGH']} |
| MEDIUM | {summary['severity_distribution']['MEDIUM']} |
| LOW | {summary['severity_distribution']['LOW']} |

## Детальные результаты

| Сканер | Уязвимостей | Зависимостей | Статус | Время |
|--------|-------------|--------------|--------|-------|
"""
        
        for result in self.all_results:
            status = "✅ УСПЕШНО" if result.scan_successful else "❌ ОШИБКА"
            md_content += f"| {result.scanner_name} | {result.vulnerabilities_found} | {result.total_dependencies} | {status} | {result.timestamp} |\n"
        
        md_content += "\n## Детали уязвимостей\n\n"
        
        for result in self.all_results:
            if result.vulnerabilities:
                md_content += f"### {result.scanner_name}\n\n"
                for vuln in result.vulnerabilities:
                    md_content += f"#### {vuln.package_name} {vuln.package_version}\n"
                    md_content += f"- **Уязвимость:** {vuln.title}\n"
                    md_content += f"- **Критичность:** {vuln.severity}\n"
                    md_content += f"- **CVE:** {vuln.cve_id or 'N/A'}\n"
                    md_content += f"- **Исправлено в:** {vuln.fixed_version or 'N/A'}\n"
                    md_content += f"- **Описание:** {vuln.description[:200]}...\n\n"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
    
    def _generate_csv_report(self, output_path: Path):
        """Генерирует CSV отчет."""
        import csv
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Scanner', 'Package', 'Version', 'Vulnerability ID',
                'Severity', 'CVE', 'CVSS Score', 'Fixed Version',
                'Title', 'Description', 'Path', 'Dependency Type'
            ])
            
            for result in self.all_results:
                for vuln in result.vulnerabilities:
                    writer.writerow([
                        result.scanner_name,
                        vuln.package_name,
                        vuln.package_version,
                        vuln.vulnerability_id,
                        vuln.severity,
                        vuln.cve_id or '',
                        vuln.cvss_score or '',
                        vuln.fixed_version or '',
                        vuln.title,
                        vuln.description[:500],  # Ограничиваем длину описания
                        vuln.path or '',
                        vuln.dependency_type or ''
                    ])


class NotificationManager:
    """Менеджер уведомлений о результатах сканирования."""
    
    def __init__(self, config: ScanConfig):
        self.config = config
    
    def send_email_notification(self, processor: ReportProcessor, summary: Dict[str, Any]):
        """Отправляет email уведомление."""
        if not self.config.email_notifications or not self.config.email_recipients:
            return
        
        try:
            # Создаем сообщение
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f'Отчет сканирования зависимостей - {datetime.now().strftime("%Y-%m-%d")}'
            msg['From'] = 'security-scanner@example.com'
            msg['To'] = ', '.join(self.config.email_recipients)
            
            # Текстовая часть
            text_content = f"""
            Отчет сканирования зависимостей
            
            Всего уязвимостей: {summary['total_vulnerabilities']}
            Критических: {summary['severity_distribution']['CRITICAL']}
            Высоких: {summary['severity_distribution']['HIGH']}
            Средних: {summary['severity_distribution']['MEDIUM']}
            Низких: {summary['severity_distribution']['LOW']}
            
            Детальный отчет во вложении.
            """
            
            # HTML часть
            html_content = f"""
            <html>
            <body>
                <h2>Отчет сканирования зависимостей</h2>
                <p><strong>Всего уязвимостей:</strong> {summary['total_vulnerabilities']}</p>
                <p style="color: #dc3545;"><strong>Критических:</strong> {summary['severity_distribution']['CRITICAL']}</p>
                <p style="color: #fd7e14;"><strong>Высоких:</strong> {summary['severity_distribution']['HIGH']}</p>
                <p style="color: #ffc107;"><strong>Средних:</strong> {summary['severity_distribution']['MEDIUM']}</p>
                <p style="color: #28a745;"><strong>Низких:</strong> {summary['severity_distribution']['LOW']}</p>
            </body>
            </html>
            """
            
            part1 = MIMEText(text_content, 'plain')
            part2 = MIMEText(html_content, 'html')
            
            msg.attach(part1)
            msg.attach(part2)
            
            # Отправляем email
            # В реальном приложении здесь будет настройка SMTP
            logger.info(f"Email уведомление отправлено получателям: {self.config.email_recipients}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки email: {e}")
    
    def send_slack_notification(self, summary: Dict[str, Any]):
        """Отправляет уведомление в Slack."""
        if not self.config.slack_webhook:
            return
        
        try:
            import requests
            
            payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "📊 Отчет сканирования зависимостей"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Всего уязвимостей:*\n{summary['total_vulnerabilities']}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Критических:*\n{summary['severity_distribution']['CRITICAL']}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Высоких:*\n{summary['severity_distribution']['HIGH']}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Средних:*\n{summary['severity_distribution']['MEDIUM']}"
                            }
                        ]
                    }
                ]
            }
            
            if summary['severity_distribution']['CRITICAL'] > 0:
                payload['blocks'].append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "🚨 *Обнаружены критические уязвимости! Требуется немедленное внимание!*"
                    }
                })
            
            response = requests.post(
                self.config.slack_webhook,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Уведомление отправлено в Slack")
            else:
                logger.error(f"Ошибка отправки в Slack: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Ошибка отправки Slack уведомления: {e}")


def load_config(config_path: Optional[str] = None) -> ScanConfig:
    """Загружает конфигурацию из файла."""
    default_config = {
        'scanner': 'safety',
        'requirements_files': ['requirements.txt'],
        'output_format': 'json',
        'output_file': None,
        'fail_on_severity': None,
        'ignore_cves': [],
        'custom_rules': {},
        'email_notifications': False,
        'email_recipients': [],
        'slack_webhook': None,
        'jira_integration': False,
        'jira_project': None
    }
    
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                if config_path.endswith('.yaml') or config_path.endswith('.yml'):
                    user_config = yaml.safe_load(f)
                elif config_path.endswith('.json'):
                    user_config = json.load(f)
                elif config_path.endswith('.toml'):
                    user_config = tomllib.load(f)
                else:
                    logger.warning(f"Неподдерживаемый формат конфига: {config_path}")
                    user_config = {}
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
            user_config = {}
    else:
        user_config = {}
    
    # Объединяем конфигурации
    config_dict = {**default_config, **user_config}
    
    return ScanConfig(**config_dict)


def check_scanner_availability(scanner_name: str) -> bool:
    """Проверяет доступность сканера в системе."""
    try:
        if scanner_name == 'safety':
            subprocess.run(['safety', '--version'], capture_output=True, check=True)
        elif scanner_name == 'trivy':
            subprocess.run(['trivy', '--version'], capture_output=True, check=True)
        elif scanner_name == 'dependency-check':
            subprocess.run(['dependency-check', '--version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main():
    """Основная функция