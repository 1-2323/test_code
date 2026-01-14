#!/usr/bin/env python3
"""
Скрипт для анализа логов на аномальное количество неудачных входов
Обнаружение атак типа brute-force и подбора учетных данных
"""

import re
import sys
import json
import time
import gzip
import argparse
import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Set, Any, Iterator
from dataclasses import dataclass, field
from collections import defaultdict, Counter
import ipaddress
import hashlib
from pathlib import Path
import sqlite3
from contextlib import contextmanager
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('attack_detection.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('attack_detector')


class LogPatterns:
    """Шаблоны для парсинга различных форматов логов"""
    
    # Общие паттерны для различных систем
    PATTERNS = {
        # Apache/nginx access logs
        'apache_access': r'(?P<ip>\d+\.\d+\.\d+\.\d+).*?"(?P<method>\w+) (?P<url>\S+) .*?" (?P<status>\d+)',
        
        # SSH неудачные попытки (Ubuntu/Debian)
        'ssh_auth_fail': r'Failed password for (?:invalid user )?(?P<user>\S+) from (?P<ip>\d+\.\d+\.\d+\.\d+)',
        
        # SSH неудачные попытки (CentOS/RHEL)
        'ssh_auth_fail_centos': r'Failed password for (?P<user>\S+) from (?P<ip>\d+\.\d+\.\d+\.\d+)',
        
        # Web auth failures (general)
        'web_auth_fail': r'(?P<ip>\d+\.\d+\.\d+\.\d+).*?(?P<status>401|403)',
        
        # WordPress login failures
        'wp_login_fail': r'POST.*?wp-login\.php.*?(?P<ip>\d+\.\d+\.\d+\.\d+)',
        
        # Custom application logs
        'custom_auth_fail': r'Authentication failed for user (?P<user>\S+) from IP (?P<ip>\d+\.\d+\.\d+\.\d+)',
        
        # Windows Event Log (Security) - 4625: Logon failure
        'windows_4625': r'Logon Failure.*?Reason:\s*(?P<reason>.*?)\s*Account Name:\s*(?P<user>.*?)\s*Account Domain:.*?Source Network Address:\s*(?P<ip>[\d\.:]+)',
    }
    
    # Поля, которые могут содержать информацию об аутентификации
    AUTH_STATUS_CODES = {'401', '403', '422'}
    FAILURE_KEYWORDS = {
        'failed', 'failure', 'invalid', 'denied', 'rejected', 
        'unauthorized', 'forbidden', 'wrong', 'incorrect'
    }


@dataclass
class FailedLoginAttempt:
    """Информация о неудачной попытке входа"""
    timestamp: datetime
    source_ip: str
    username: Optional[str]
    target_service: str
    failure_reason: Optional[str]
    raw_log_line: str
    log_source: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'source_ip': self.source_ip,
            'username': self.username,
            'target_service': self.target_service,
            'failure_reason': self.failure_reason,
            'log_source': self.log_source,
            'raw_log': self.raw_log_line[:500]  # Ограничение длины
        }


@dataclass
class AttackPattern:
    """Обнаруженный паттерн атаки"""
    pattern_type: str
    source_ip: str
    start_time: datetime
    end_time: datetime
    attempt_count: int
    target_usernames: Set[str]
    target_services: Set[str]
    severity: str
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'pattern_type': self.pattern_type,
            'source_ip': self.source_ip,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat(),
            'attempt_count': self.attempt_count,
            'target_usernames': list(self.target_usernames),
            'target_services': list(self.target_services),
            'severity': self.severity,
            'confidence': round(self.confidence, 2),
            'details': self.details
        }


class LogParser:
    """Парсер логов различных форматов"""
    
    def __init__(self, log_format: str = 'auto'):
        self.log_format = log_format
        self.compiled_patterns = {}
        
        # Компиляция паттернов
        for name, pattern in LogPatterns.PATTERNS.items():
            self.compiled_patterns[name] = re.compile(pattern)
    
    def parse_line(self, line: str, log_source: str) -> Optional[FailedLoginAttempt]:
        """Парсинг одной строки лога"""
        line = line.strip()
        if not line:
            return None
        
        # Определение формата лога
        log_format = self._detect_log_format(line)
        if not log_format:
            return None
        
        # Попытка извлечения IP адреса
        ip_address = self._extract_ip_address(line)
        if not ip_address:
            return None
        
        # Определение таймстемпа
        timestamp = self._extract_timestamp(line)
        if not timestamp:
            timestamp = datetime.now()
        
        # Определение имени пользователя
        username = self._extract_username(line, log_format)
        
        # Определение причины ошибки
        failure_reason = self._extract_failure_reason(line)
        
        # Определение целевого сервиса
        target_service = self._determine_target_service(line, log_format)
        
        # Проверка, является ли это неудачной попыткой входа
        if self._is_failed_login(line, log_format):
            return FailedLoginAttempt(
                timestamp=timestamp,
                source_ip=ip_address,
                username=username,
                target_service=target_service,
                failure_reason=failure_reason,
                raw_log_line=line,
                log_source=log_source
            )
        
        return None
    
    def _detect_log_format(self, line: str) -> Optional[str]:
        """Автоматическое определение формата лога"""
        if self.log_format != 'auto':
            return self.log_format
        
        # Проверка SSH логов
        if 'sshd' in line.lower() and 'failed password' in line.lower():
            if 'invalid user' in line.lower():
                return 'ssh_auth_fail'
            else:
                return 'ssh_auth_fail_centos'
        
        # Проверка веб логов
        if any(method in line for method in ['POST', 'GET', 'PUT', 'DELETE']):
            if 'wp-login.php' in line:
                return 'wp_login_fail'
            return 'apache_access'
        
        # Проверка Windows Event Log
        if '4625' in line and 'Logon Failure' in line:
            return 'windows_4625'
        
        # Проверка кастомных логов
        if 'authentication failed' in line.lower():
            return 'custom_auth_fail'
        
        return None
    
    def _extract_ip_address(self, line: str) -> Optional[str]:
        """Извлечение IP адреса из строки лога"""
        # Регулярное выражение для IPv4
        ipv4_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
        ipv4_match = re.search(ipv4_pattern, line)
        
        if ipv4_match:
            ip = ipv4_match.group(0)
            try:
                # Валидация IP адреса
                ipaddress.IPv4Address(ip)
                return ip
            except (ipaddress.AddressValueError, ValueError):
                pass
        
        # Регулярное выражение для IPv6
        ipv6_pattern = r'\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b'
        ipv6_match = re.search(ipv6_pattern, line)
        
        if ipv6_match:
            ip = ipv6_match.group(0)
            try:
                ipaddress.IPv6Address(ip)
                return ip
            except (ipaddress.AddressValueError, ValueError):
                pass
        
        return None
    
    def _extract_timestamp(self, line: str) -> Optional[datetime]:
        """Извлечение временной метки из строки лога"""
        # Общие форматы временных меток
        timestamp_patterns = [
            # Apache/Nginx: [10/Oct/2000:13:55:36 -0700]
            r'\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+\-]\d{4})\]',
            
            # Syslog: Oct 10 13:55:36
            r'(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})',
            
            # ISO 8601: 2000-10-10T13:55:36Z
            r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})',
            
            # Windows Event Log
            r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} [AP]M)',
        ]
        
        for pattern in timestamp_patterns:
            match = re.search(pattern, line)
            if match:
                timestamp_str = match.group(1)
                try:
                    # Попытка парсинга различных форматов
                    for fmt in [
                        '%d/%b/%Y:%H:%M:%S %z',
                        '%b %d %H:%M:%S',
                        '%Y-%m-%d %H:%M:%S',
                        '%Y-%m-%dT%H:%M:%S',
                        '%m/%d/%Y %I:%M:%S %p'
                    ]:
                        try:
                            return datetime.strptime(timestamp_str, fmt)
                        except ValueError:
                            continue
                except Exception:
                    pass
        
        return None
    
    def _extract_username(self, line: str, log_format: str) -> Optional[str]:
        """Извлечение имени пользователя"""
        if log_format in self.compiled_patterns:
            match = self.compiled_patterns[log_format].search(line)
            if match and 'user' in match.groupdict():
                return match.group('user')
        
        # Поиск имени пользователя в общем формате
        user_patterns = [
            r'user[=:]\s*([^\s,]+)',
            r'username[=:]\s*([^\s,]+)',
            r'login[=:]\s*([^\s,]+)',
            r'for user (\S+)',
            r'user (\S+) failed',
        ]
        
        for pattern in user_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_failure_reason(self, line: str) -> Optional[str]:
        """Извлечение причины ошибки"""
        for keyword in LogPatterns.FAILURE_KEYWORDS:
            if keyword in line.lower():
                # Извлечение контекста вокруг ключевого слова
                start = max(0, line.lower().find(keyword) - 50)
                end = min(len(line), line.lower().find(keyword) + len(keyword) + 50)
                return line[start:end].strip()
        
        return None
    
    def _determine_target_service(self, line: str, log_format: str) -> str:
        """Определение целевого сервиса"""
        service_map = {
            'ssh_auth_fail': 'SSH',
            'ssh_auth_fail_centos': 'SSH',
            'apache_access': 'HTTP',
            'wp_login_fail': 'WordPress',
            'windows_4625': 'Windows Authentication',
            'custom_auth_fail': 'Custom Application'
        }
        
        return service_map.get(log_format, 'Unknown')
    
    def _is_failed_login(self, line: str, log_format: str) -> bool:
        """Определение, является ли строка лога неудачной попыткой входа"""
        line_lower = line.lower()
        
        # Проверка по ключевым словам
        for keyword in LogPatterns.FAILURE_KEYWORDS:
            if keyword in line_lower:
                return True
        
        # Проверка кодов состояния HTTP
        if log_format == 'apache_access':
            status_match = re.search(r'\s(\d{3})\s', line)
            if status_match and status_match.group(1) in LogPatterns.AUTH_STATUS_CODES:
                return True
        
        # Проверка специфичных для формата паттернов
        if log_format in ['ssh_auth_fail', 'ssh_auth_fail_centos', 'windows_4625']:
            return True
        
        return False


class AttackDetector:
    """Детектор аномальной активности"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Пороговые значения для детекции
        self.thresholds = {
            'bruteforce': {
                'attempts_per_minute': 10,
                'attempts_per_hour': 50,
                'unique_usernames': 5
            },
            'credential_stuffing': {
                'attempts_per_ip': 100,
                'time_window_minutes': 5
            },
            'distributed_attack': {
                'unique_ips_per_user': 3,
                'attempts_per_user': 20
            }
        }
        
        # Обновление порогов из конфигурации
        if 'thresholds' in config:
            self.thresholds.update(config['thresholds'])
        
        # Хранилище данных
        self.attempts_by_ip: Dict[str, List[FailedLoginAttempt]] = defaultdict(list)
        self.attempts_by_user: Dict[str, List[FailedLoginAttempt]] = defaultdict(list)
        
        # Кэш для ускорения анализа
        self.ip_blacklist: Set[str] = set()
        self.ip_whitelist: Set[str] = set()
        
        # Загрузка белого/черного списков
        self._load_ip_lists()
    
    def _load_ip_lists(self):
        """Загрузка белого и черного списков IP адресов"""
        try:
            # Черный список
            blacklist_file = self.config.get('blacklist_file')
            if blacklist_file and Path(blacklist_file).exists():
                with open(blacklist_file, 'r') as f:
                    for line in f:
                        ip = line.strip()
                        if ip and not ip.startswith('#'):
                            self.ip_blacklist.add(ip)
            
            # Белый список
            whitelist_file = self.config.get('whitelist_file')
            if whitelist_file and Path(whitelist_file).exists():
                with open(whitelist_file, 'r') as f:
                    for line in f:
                        ip = line.strip()
                        if ip and not ip.startswith('#'):
                            self.ip_whitelist.add(ip)
        
        except Exception as e:
            logger.warning(f"Failed to load IP lists: {e}")
    
    def analyze_attempts(self, attempts: List[FailedLoginAttempt]) -> List[AttackPattern]:
        """Анализ попыток входа на предмет аномальной активности"""
        if not attempts:
            return []
        
        # Группировка попыток
        self._group_attempts(attempts)
        
        # Обнаружение различных типов атак
        detected_attacks = []
        
        # 1. Обнаружение brute-force атак
        bruteforce_attacks = self._detect_bruteforce()
        detected_attacks.extend(bruteforce_attacks)
        
        # 2. Обнаружение credential stuffing
        credential_stuffing = self._detect_credential_stuffing()
        detected_attacks.extend(credential_stuffing)
        
        # 3. Обнаружение распределенных атак
        distributed_attacks = self._detect_distributed_attacks()
        detected_attacks.extend(distributed_attacks)
        
        # 4. Обнаружение подозрительных паттернов
        suspicious_patterns = self._detect_suspicious_patterns()
        detected_attacks.extend(suspicious_patterns)
        
        # Фильтрация атак из белого списка
        filtered_attacks = []
        for attack in detected_attacks:
            if attack.source_ip not in self.ip_whitelist:
                filtered_attacks.append(attack)
        
        return filtered_attacks
    
    def _group_attempts(self, attempts: List[FailedLoginAttempt]):
        """Группировка попыток по IP и пользователю"""
        for attempt in attempts:
            # Пропускаем попытки из белого списка
            if attempt.source_ip in self.ip_whitelist:
                continue
            
            self.attempts_by_ip[attempt.source_ip].append(attempt)
            
            if attempt.username:
                self.attempts_by_user[attempt.username].append(attempt)
    
    def _detect_bruteforce(self) -> List[AttackPattern]:
        """Обнаружение brute-force атак"""
        attacks = []
        threshold = self.thresholds['bruteforce']
        
        for ip, attempts in self.attempts_by_ip.items():
            if not attempts:
                continue
            
            # Сортировка по времени
            attempts.sort(key=lambda x: x.timestamp)
            
            # Анализ за последний час
            one_hour_ago = datetime.now() - timedelta(hours=1)
            recent_attempts = [
                a for a in attempts if a.timestamp >= one_hour_ago
            ]
            
            if len(recent_attempts) < threshold['attempts_per_hour']:
                continue
            
            # Анализ по минутам
            attempts_by_minute = defaultdict(int)
            for attempt in recent_attempts:
                minute_key = attempt.timestamp.replace(second=0, microsecond=0)
                attempts_by_minute[minute_key] += 1
            
            # Поиск минут с высокой активностью
            for minute, count in attempts_by_minute.items():
                if count >= threshold['attempts_per_minute']:
                    # Вычисление уникальных пользователей
                    unique_users = len(set(
                        a.username for a in recent_attempts 
                        if a.username and 
                        abs((a.timestamp - minute).total_seconds()) <= 60
                    ))
                    
                    # Определение серьезности атаки
                    severity = self._calculate_severity(
                        count, 
                        threshold['attempts_per_minute']
                    )
                    
                    # Расчет уверенности
                    confidence = self._calculate_confidence(
                        count, 
                        unique_users,
                        threshold['attempts_per_minute'],
                        threshold['unique_usernames']
                    )
                    
                    attack = AttackPattern(
                        pattern_type='BRUTEFORCE',
                        source_ip=ip,
                        start_time=minute,
                        end_time=minute + timedelta(minutes=1),
                        attempt_count=count,
                        target_usernames=set(
                            a.username for a in recent_attempts 
                            if a.username and 
                            abs((a.timestamp - minute).total_seconds()) <= 60
                        ),
                        target_services=set(
                            a.target_service for a in recent_attempts 
                            if abs((a.timestamp - minute).total_seconds()) <= 60
                        ),
                        severity=severity,
                        confidence=confidence,
                        details={
                            'attempts_per_minute': count,
                            'unique_usernames': unique_users,
                            'time_window': '1 minute'
                        }
                    )
                    attacks.append(attack)
        
        return attacks
    
    def _detect_credential_stuffing(self) -> List[AttackPattern]:
        """Обнаружение credential stuffing атак"""
        attacks = []
        threshold = self.thresholds['credential_stuffing']
        
        for ip, attempts in self.attempts_by_ip.items():
            if not attempts:
                continue
            
            attempts.sort(key=lambda x: x.timestamp)
            
            # Проверка за временное окно
            if len(attempts) >= threshold['attempts_per_ip']:
                # Проверка временного окна
                time_window = threshold['time_window_minutes']
                start_time = attempts[0].timestamp
                end_time = attempts[-1].timestamp
                window_duration = (end_time - start_time).total_seconds() / 60
                
                if window_duration <= time_window:
                    # Анализ разнообразия имен пользователей
                    usernames = [a.username for a in attempts if a.username]
                    unique_usernames = len(set(usernames))
                    
                    # Проверка на использование общих паролей/имен пользователей
                    is_credential_stuffing = (
                        unique_usernames > 10 and  # Много разных пользователей
                        len(attempts) / unique_usernames < 3  # Несколько попыток на пользователя
                    )
                    
                    if is_credential_stuffing:
                        severity = self._calculate_severity(
                            len(attempts),
                            threshold['attempts_per_ip']
                        )
                        
                        confidence = min(0.95, len(attempts) / 200)
                        
                        attack = AttackPattern(
                            pattern_type='CREDENTIAL_STUFFING',
                            source_ip=ip,
                            start_time=start_time,
                            end_time=end_time,
                            attempt_count=len(attempts),
                            target_usernames=set(usernames),
                            target_services=set(a.target_service for a in attempts),
                            severity=severity,
                            confidence=confidence,
                            details={
                                'total_attempts': len(attempts),
                                'unique_usernames': unique_usernames,
                                'time_window_minutes': window_duration
                            }
                        )
                        attacks.append(attack)
        
        return attacks
    
    def _detect_distributed_attacks(self) -> List[AttackPattern]:
        """Обнаружение распределенных атак"""
        attacks = []
        threshold = self.thresholds['distributed_attack']
        
        for username, user_attempts in self.attempts_by_user.items():
            if not username or not user_attempts:
                continue
            
            if len(user_attempts) < threshold['attempts_per_user']:
                continue
            
            # Группировка по IP адресам
            ips_by_attempt = defaultdict(list)
            for attempt in user_attempts:
                ips_by_attempt[attempt.source_ip].append(attempt)
            
            unique_ips = len(ips_by_attempt)
            
            if unique_ips >= threshold['unique_ips_per_user']:
                # Проверка временного окна
                start_time = min(a.timestamp for a in user_attempts)
                end_time = max(a.timestamp for a in user_attempts)
                time_window = (end_time - start_time).total_seconds() / 60
                
                # Среднее количество попыток на IP
                avg_attempts_per_ip = len(user_attempts) / unique_ips
                
                # Определение атаки
                if time_window < 60 and avg_attempts_per_ip < 5:  # Распределенная атака
                    severity = 'HIGH'
                    confidence = min(0.9, unique_ips / 10)
                    
                    attack = AttackPattern(
                        pattern_type='DISTRIBUTED_ATTACK',
                        source_ip='MULTIPLE_IPS',
                        start_time=start_time,
                        end_time=end_time,
                        attempt_count=len(user_attempts),
                        target_usernames={username},
                        target_services=set(a.target_service for a in user_attempts),
                        severity=severity,
                        confidence=confidence,
                        details={
                            'target_username': username,
                            'unique_source_ips': unique_ips,
                            'average_attempts_per_ip': round(avg_attempts_per_ip, 2),
                            'time_window_minutes': round(time_window, 2)
                        }
                    )
                    attacks.append(attack)
        
        return attacks
    
    def _detect_suspicious_patterns(self) -> List[AttackPattern]:
        """Обнаружение подозрительных паттернов"""
        attacks = []
        
        # Паттерн 1: Быстрая смена пользователей с одного IP
        for ip, attempts in self.attempts_by_ip.items():
            if len(attempts) < 20:
                continue
            
            attempts.sort(key=lambda x: x.timestamp)
            
            # Проверка скорости смены пользователей
            username_changes = 0
            last_username = None
            
            for attempt in attempts:
                if attempt.username and attempt.username != last_username:
                    username_changes += 1
                    last_username = attempt.username
            
            if username_changes > 10:
                # Высокая скорость смены пользователей
                start_time = attempts[0].timestamp
                end_time = attempts[-1].timestamp
                time_window = (end_time - start_time).total_seconds() / 60
                
                if time_window < 10:  # 10 минут
                    attack = AttackPattern(
                        pattern_type='RAPID_USER_SWITCHING',
                        source_ip=ip,
                        start_time=start_time,
                        end_time=end_time,
                        attempt_count=len(attempts),
                        target_usernames=set(a.username for a in attempts if a.username),
                        target_services=set(a.target_service for a in attempts),
                        severity='MEDIUM',
                        confidence=0.7,
                        details={
                            'username_changes': username_changes,
                            'time_window_minutes': round(time_window, 2)
                        }
                    )
                    attacks.append(attack)
        
        # Паттерн 2: Попытки к несуществующим пользователям
        common_users = {'admin', 'root', 'administrator', 'test', 'user'}
        for ip, attempts in self.attempts_by_ip.items():
            invalid_user_attempts = [
                a for a in attempts 
                if a.username and 'invalid' in a.raw_log_line.lower()
            ]
            
            if len(invalid_user_attempts) > 5:
                start_time = invalid_user_attempts[0].timestamp
                end_time = invalid_user_attempts[-1].timestamp
                
                attack = AttackPattern(
                    pattern_type='INVALID_USER_ATTEMPTS',
                    source_ip=ip,
                    start_time=start_time,
                    end_time=end_time,
                    attempt_count=len(invalid_user_attempts),
                    target_usernames=set(a.username for a in invalid_user_attempts),
                    target_services=set(a.target_service for a in invalid_user_attempts),
                    severity='LOW',
                    confidence=0.6,
                    details={
                        'invalid_user_attempts': len(invalid_user_attempts)
                    }
                )
                attacks.append(attack)
        
        return attacks
    
    def _calculate_severity(self, actual: int, threshold: int) -> str:
        """Расчет серьезности атаки"""
        ratio = actual / threshold
        
        if ratio >= 10:
            return 'CRITICAL'
        elif ratio >= 5:
            return 'HIGH'
        elif ratio >= 2:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def _calculate_confidence(self, attempts: int, unique_users: int, 
                            threshold_attempts: int, threshold_users: int) -> float:
        """Расчет уверенности в обнаружении атаки"""
        attempt_ratio = min(1.0, attempts / (threshold_attempts * 2))
        user_ratio = min(1.0, unique_users / (threshold_users * 2))
        
        confidence = (attempt_ratio * 0.7) + (user_ratio * 0.3)
        return min(0.99, confidence)


class LogDatabase:
    """База данных для хранения логов и результатов анализа"""
    
    def __init__(self, db_path: str = 'attack_detection.db'):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица для неудачных попыток входа
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS failed_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                source_ip TEXT,
                username TEXT,
                target_service TEXT,
                failure_reason TEXT,
                log_source TEXT,
                raw_log TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица для обнаруженных атак
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS detected_attacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT,
                source_ip TEXT,
                start_time DATETIME,
                end_time DATETIME,
                attempt_count INTEGER,
                target_usernames TEXT,
                target_services TEXT,
                severity TEXT,
                confidence REAL,
                details TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Индексы для ускорения запросов
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_attempts_ip ON failed_attempts(source_ip)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_attempts_time ON failed_attempts(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_attacks_ip ON detected_attacks(source_ip)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_attacks_time ON detected_attacks(start_time)')
        
        conn.commit()
        conn.close()
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для соединения с БД"""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()
    
    def store_failed_attempts(self, attempts: List[FailedLoginAttempt]):
        """Сохранение неудачных попыток в БД"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for attempt in attempts:
                cursor.execute('''
                    INSERT INTO failed_attempts 
                    (timestamp, source_ip, username, target_service, failure_reason, log_source, raw_log)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    attempt.timestamp,
                    attempt.source_ip,
                    attempt.username,
                    attempt.target_service,
                    attempt.failure_reason,
                    attempt.log_source,
                    attempt.raw_log_line
                ))
            
            conn.commit()
    
    def store_detected_attacks(self, attacks: List[AttackPattern]):
        """Сохранение обнаруженных атак в БД"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for attack in attacks:
                cursor.execute('''
                    INSERT INTO detected_attacks 
                    (pattern_type, source_ip, start_time, end_time, attempt_count, 
                     target_usernames, target_services, severity, confidence, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    attack.pattern_type,
                    attack.source_ip,
                    attack.start_time,
                    attack.end_time,
                    attack.attempt_count,
                    json.dumps(list(attack.target_usernames)),
                    json.dumps(list(attack.target_services)),
                    attack.severity,
                    attack.confidence,
                    json.dumps(attack.details)
                ))
            
            conn.commit()


class ReportGenerator:
    """Генератор отчетов об обнаруженных атаках"""
    
    def __init__(self, output_dir: str = 'reports'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def generate_report(self, attacks: List[AttackPattern], 
                       analysis_period: Tuple[datetime, datetime]) -> Path:
        """Генерация отчета в формате HTML"""
        report_time = datetime.now()
        report_id = hashlib.md5(str(report_time).encode()).hexdigest()[:8]
        
        # Статистика атак
        attack_stats = self._calculate_attack_statistics(attacks)
        
        # Генерация HTML отчета
        html_content = self._generate_html_report(
            attacks, attack_stats, analysis_period, report_time, report_id
        )
        
        # Сохранение отчета
        report_filename = f"attack_report_{report_time.strftime('%Y%m%d_%H%M%S')}_{report_id}.html"
        report_path = self.output_dir / report_filename
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Генерация JSON отчета
        json_report = self._generate_json_report(attacks, attack_stats)
        json_path = self.output_dir / f"attack_report_{report_time.strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_report, f, indent=2, default=str)
        
        logger.info(f"Report generated: {report_path}")
        return report_path
    
    def _calculate_attack_statistics(self, attacks: List[AttackPattern]) -> Dict[str, Any]:
        """Расчет статистики атак"""
        if not attacks:
            return {}
        
        # Группировка по типу атаки
        attacks_by_type = defaultdict(list)
        for attack in attacks:
            attacks_by_type[attack.pattern_type].append(attack)
        
        # Статистика по IP адресам
        source_ips = set(attack.source_ip for attack in attacks)
        
        # Общее количество попыток
        total_attempts = sum(attack.attempt_count for attack in attacks)
        
        # Распределение по серьезности
        severity_distribution = Counter(attack.severity for attack in attacks)
        
        return {
            'total_attacks': len(attacks),
            'unique_source_ips': len(source_ips),
            'total_attempts': total_attempts,
            'attacks_by_type': {k: len(v) for k, v in attacks_by_type.items()},
            'severity_distribution': dict(severity_distribution),
            'average_confidence': round(
                statistics.mean(attack.confidence for attack in attacks), 2
            ) if attacks else 0
        }
    
    def _generate_html_report(self, attacks: List[AttackPattern], 
                            stats: Dict[str, Any], 
                            analysis_period: Tuple[datetime, datetime],
                            report_time: datetime, 
                            report_id: str) -> str:
        """Генерация HTML отчета"""
        start_time, end_time = analysis_period
        
        html = f'''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Attack Detection Report - {report_time.strftime('%Y-%m-%d %H:%M:%S')}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #