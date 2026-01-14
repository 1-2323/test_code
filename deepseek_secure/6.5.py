#!/usr/bin/env python3
"""
Скрипт для автоматизированного сканирования зависимостей на наличие известных уязвимостей
"""

import json
import subprocess
import sys
import os
import argparse
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging

# Конфигурация логгера
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Vulnerability:
    """Класс для представления информации об уязвимости"""
    package_name: str
    installed_version: str
    fixed_version: Optional[str]
    severity: str
    description: str
    cve_id: Optional[str]
    advisory_url: Optional[str]


class DependencyScanner:
    """Основной класс для сканирования зависимостей"""
    
    def __init__(self, tool_path: Optional[str] = None):
        """
        Инициализация сканера
        
        Args:
            tool_path: Путь к инструменту сканирования (если не в PATH)
        """
        self.tool_path = tool_path or self._detect_scanner()
        self.vulnerabilities: List[Vulnerability] = []
        
    def _detect_scanner(self) -> str:
        """
        Автоматическое определение доступного сканера
        
        Returns:
            Название найденного инструмента
        """
        scanners = ['trivy', 'grype', 'dependency-check', 'snyk']
        
        for scanner in scanners:
            try:
                subprocess.run(
                    [scanner, '--version'],
                    capture_output=True,
                    check=False
                )
                logger.info(f"Найден сканер: {scanner}")
                return scanner
            except FileNotFoundError:
                continue
                
        raise RuntimeError(
            "Не найден ни один сканер уязвимостей. "
            "Установите один из: trivy, grype, dependency-check, snyk"
        )
    
    def _parse_trivy_output(self, report: Dict[str, Any]) -> List[Vulnerability]:
        """Парсинг вывода Trivy"""
        vulnerabilities = []
        
        if 'Results' not in report:
            return vulnerabilities
            
        for result in report['Results']:
            if 'Vulnerabilities' not in result:
                continue
                
            for vuln in result['Vulnerabilities']:
                vulnerability = Vulnerability(
                    package_name=vuln.get('PkgName', 'Unknown'),
                    installed_version=vuln.get('InstalledVersion', 'Unknown'),
                    fixed_version=vuln.get('FixedVersion'),
                    severity=vuln.get('Severity', 'Unknown'),
                    description=vuln.get('Description', ''),
                    cve_id=vuln.get('VulnerabilityID'),
                    advisory_url=vuln.get('PrimaryURL')
                )
                vulnerabilities.append(vulnerability)
                
        return vulnerabilities
    
    def _parse_grype_output(self, report: Dict[str, Any]) -> List[Vulnerability]:
        """Парсинг вывода Grype"""
        vulnerabilities = []
        
        if 'matches' not in report:
            return vulnerabilities
            
        for match in report['matches']:
            artifact = match.get('artifact', {})
            vulnerability = match.get('vulnerability', {})
            
            vuln_obj = Vulnerability(
                package_name=artifact.get('name', 'Unknown'),
                installed_version=artifact.get('version', 'Unknown'),
                fixed_version=self._extract_fixed_version(match),
                severity=vulnerability.get('severity', 'Unknown'),
                description=vulnerability.get('description', ''),
                cve_id=vulnerability.get('id'),
                advisory_url=vulnerability.get('dataSource')
            )
            vulnerabilities.append(vuln_obj)
            
        return vulnerabilities
    
    def _extract_fixed_version(self, match_data: Dict[str, Any]) -> Optional[str]:
        """Извлечение информации о фиксированной версии"""
        if 'fix' in match_data and 'versions' in match_data['fix']:
            versions = match_data['fix']['versions']
            if versions:
                return versions[0]
        return None
    
    def _parse_dependency_check_output(self, report: Dict[str, Any]) -> List[Vulnerability]:
        """Парсинг вывода OWASP Dependency-Check"""
        vulnerabilities = []
        
        if 'dependencies' not in report:
            return vulnerabilities
            
        for dep in report['dependencies']:
            if 'vulnerabilities' not in dep:
                continue
                
            for vuln in dep['vulnerabilities']:
                vulnerability = Vulnerability(
                    package_name=dep.get('fileName', 'Unknown'),
                    installed_version=dep.get('version', 'Unknown'),
                    fixed_version=None,  # Dependency-Check не всегда предоставляет
                    severity=vuln.get('severity', 'Unknown'),
                    description=vuln.get('description', ''),
                    cve_id=vuln.get('name'),
                    advisory_url=vuln.get('reference')
                )
                vulnerabilities.append(vulnerability)
                
        return vulnerabilities
    
    def scan_project(self, target_path: str, output_format: str = 'json') -> bool:
        """
        Сканирование проекта на уязвимости
        
        Args:
            target_path: Путь к сканируемому проекту
            output_format: Формат вывода (json, table)
            
        Returns:
            True если найдены уязвимости, иначе False
        """
        logger.info(f"Начинаем сканирование: {target_path}")
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_file:
            report_path = tmp_file.name
            
            try:
                # Запуск сканера
                cmd = [self.tool_path, target_path, '-f', 'json', '-o', report_path]
                
                if self.tool_path == 'dependency-check':
                    cmd = [self.tool_path, '--scan', target_path, '--format', 'JSON', '--out', report_path]
                
                logger.info(f"Выполняем команду: {' '.join(cmd)}")
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode != 0 and result.returncode != 1:  # 1 - найдены уязвимости
                    logger.error(f"Ошибка сканирования: {result.stderr}")
                    return False
                    
                # Чтение и парсинг отчета
                with open(report_path, 'r') as f:
                    report_data = json.load(f)
                
                # Парсинг в зависимости от инструмента
                if self.tool_path == 'trivy':
                    self.vulnerabilities = self._parse_trivy_output(report_data)
                elif self.tool_path == 'grype':
                    self.vulnerabilities = self._parse_grype_output(report_data)
                elif self.tool_path == 'dependency-check':
                    self.vulnerabilities = self._parse_dependency_check_output(report_data)
                else:
                    logger.warning(f"Парсер для {self.tool_path} не реализован")
                    return False
                    
                # Генерация отчета
                self._generate_report(output_format)
                
                return len(self.vulnerabilities) > 0
                
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга JSON: {e}")
                return False
            except Exception as e:
                logger.error(f"Неожиданная ошибка: {e}")
                return False
            finally:
                # Удаление временного файла
                if os.path.exists(report_path):
                    os.unlink(report_path)
    
    def _generate_report(self, output_format: str):
        """Генерация отчета о найденных уязвимостях"""
        if not self.vulnerabilities:
            logger.info("Уязвимостей не найдено")
            return
        
        logger.warning(f"Найдено уязвимостей: {len(self.vulnerabilities)}")
        
        if output_format == 'json':
            self._generate_json_report()
        else:
            self._generate_table_report()
    
    def _generate_json_report(self):
        """Генерация отчета в формате JSON"""
        report = {
            'scan_date': datetime.now().isoformat(),
            'scanner': self.tool_path,
            'vulnerabilities_found': len(self.vulnerabilities),
            'vulnerabilities': [
                {
                    'package': vuln.package_name,
                    'installed_version': vuln.installed_version,
                    'fixed_version': vuln.fixed_version,
                    'severity': vuln.severity,
                    'cve': vuln.cve_id,
                    'description': vuln.description[:200] + '...' if len(vuln.description) > 200 else vuln.description,
                    'advisory': vuln.advisory_url
                }
                for vuln in self.vulnerabilities
            ]
        }
        
        output_file = f"vulnerability_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"JSON отчет сохранен: {output_file}")
    
    def _generate_table_report(self):
        """Генерация табличного отчета"""
        print("\n" + "="*120)
        print(f"{'УЯЗВИМОСТИ ЗАВИСИМОСТЕЙ':^120}")
        print(f"Дата сканирования: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Сканер: {self.tool_path}")
        print(f"Найдено уязвимостей: {len(self.vulnerabilities)}")
        print("="*120)
        
        headers = ["Пакет", "Версия", "Исправлено", "Уровень", "CVE ID", "Описание"]
        print(f"{headers[0]:<20} {headers[1]:<15} {headers[2]:<15} {headers[3]:<10} {headers[4]:<15} {headers[5]:<30}")
        print("-"*120)
        
        for vuln in self.vulnerabilities:
            desc_short = vuln.description[:30] + '...' if len(vuln.description) > 30 else vuln.description
            print(
                f"{vuln.package_name:<20} "
                f"{vuln.installed_version:<15} "
                f"{vuln.fixed_version or 'N/A':<15} "
                f"{vuln.severity:<10} "
                f"{vuln.cve_id or 'N/A':<15} "
                f"{desc_short:<30}"
            )
        
        # Статистика по уровням серьезности
        severity_counts = {}
        for vuln in self.vulnerabilities:
            severity_counts[vuln.severity] = severity_counts.get(vuln.severity, 0) + 1
        
        print("\n" + "="*120)
        print("СТАТИСТИКА:")
        for severity, count in sorted(severity_counts.items()):
            print(f"  {severity}: {count}")
        print("="*120)
    
    def get_summary(self) -> Dict[str, Any]:
        """Получение сводной информации о сканировании"""
        severity_counts = {}
        for vuln in self.vulnerabilities:
            severity_counts[vuln.severity] = severity_counts.get(vuln.severity, 0) + 1
        
        return {
            'total_vulnerabilities': len(self.vulnerabilities),
            'severity_counts': severity_counts,
            'has_critical': any(v.severity.lower() == 'critical' for v in self.vulnerabilities),
            'has_high': any(v.severity.lower() == 'high' for v in self.vulnerabilities),
            'scanner_used': self.tool_path
        }


def main():
    """Основная функция"""
    parser = argparse.ArgumentParser(
        description='Сканирование зависимостей на уязвимости'
    )
    parser.add_argument(
        'target',
        help='Путь к сканируемому проекту или файлу манифеста'
    )
    parser.add_argument(
        '--scanner',
        help='Инструмент сканирования (trivy, grype, dependency-check)',
        default=None
    )
    parser.add_argument(
        '--format',
        help='Формат вывода (json, table)',
        choices=['json', 'table'],
        default='table'
    )
    parser.add_argument(
        '--output',
        help='Путь для сохранения отчета',
        default=None
    )
    parser.add_argument(
        '--verbose',
        help='Подробный вывод',
        action='store_true'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Проверка существования целевого пути
    if not os.path.exists(args.target):
        logger.error(f"Путь не существует: {args.target}")
        sys.exit(1)
    
    try:
        # Инициализация сканера
        scanner = DependencyScanner(args.scanner)
        
        # Выполнение сканирования
        vulnerabilities_found = scanner.scan_project(args.target, args.format)
        
        # Вывод сводки
        summary = scanner.get_summary()
        logger.info(f"Сканирование завершено. Найдено уязвимостей: {summary['total_vulnerabilities']}")
        
        if vulnerabilities_found:
            logger.warning("Обнаружены уязвимости!")
            if summary['has_critical']:
                logger.error("КРИТИЧЕСКИЕ уязвимости требуют немедленного внимания!")
            sys.exit(1)
        else:
            logger.info("Критических уязвимостей не обнаружено")
            sys.exit(0)
            
    except RuntimeError as e:
        logger.error(f"Ошибка инициализации: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Сканирование прервано пользователем")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()