import time
import logging
import threading
import schedule
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import json
import smtplib
import requests
import pymysql
import psycopg2
import redis
import pymongo
from pymongo import MongoClient
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket
import ssl
import sys

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('health_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('health_monitor')


class ServiceStatus(Enum):
    """Статусы сервисов"""
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class ServiceType(Enum):
    """Типы сервисов"""
    DATABASE = "DATABASE"
    API = "API"
    CACHE = "CACHE"
    MESSAGE_QUEUE = "MESSAGE_QUEUE"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"


@dataclass
class HealthCheckResult:
    """Результат проверки здоровья"""
    service_name: str
    service_type: ServiceType
    status: ServiceStatus
    response_time: float  # в миллисекундах
    timestamp: datetime
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ServiceConfig:
    """Конфигурация сервиса для мониторинга"""
    name: str
    service_type: ServiceType
    check_interval: int  # в секундах
    timeout: int = 5
    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)


class DatabaseChecker:
    """Проверка соединения с базами данных"""
    
    @staticmethod
    def check_mysql(host: str, port: int, user: str, password: str, 
                   database: str, timeout: int) -> HealthCheckResult:
        """Проверка MySQL"""
        start_time = time.time()
        service_name = f"MySQL_{host}_{database}"
        
        try:
            connection = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connect_timeout=timeout,
                cursorclass=pymysql.cursors.DictCursor
            )
            
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 as health_check")
                result = cursor.fetchone()
            
            connection.close()
            
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.DATABASE,
                status=ServiceStatus.HEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                details={"version": connection.get_server_info()}
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.DATABASE,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message=str(e)
            )
    
    @staticmethod
    def check_postgresql(host: str, port: int, user: str, password: str,
                        database: str, timeout: int) -> HealthCheckResult:
        """Проверка PostgreSQL"""
        start_time = time.time()
        service_name = f"PostgreSQL_{host}_{database}"
        
        try:
            connection = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connect_timeout=timeout
            )
            
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 as health_check")
                result = cursor.fetchone()
            
            connection.close()
            
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.DATABASE,
                status=ServiceStatus.HEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                details={"server_version": connection.server_version}
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.DATABASE,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message=str(e)
            )
    
    @staticmethod
    def check_redis(host: str, port: int, password: Optional[str],
                   timeout: int) -> HealthCheckResult:
        """Проверка Redis"""
        start_time = time.time()
        service_name = f"Redis_{host}_{port}"
        
        try:
            redis_client = redis.Redis(
                host=host,
                port=port,
                password=password,
                socket_timeout=timeout,
                socket_connect_timeout=timeout
            )
            
            # Проверка соединения
            redis_client.ping()
            
            # Получение информации о сервере
            info = redis_client.info()
            
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.CACHE,
                status=ServiceStatus.HEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                details={
                    "version": info.get('redis_version'),
                    "used_memory": info.get('used_memory_human')
                }
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.CACHE,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message=str(e)
            )
    
    @staticmethod
    def check_mongodb(host: str, port: int, username: Optional[str],
                     password: Optional[str], database: str,
                     timeout: int) -> HealthCheckResult:
        """Проверка MongoDB"""
        start_time = time.time()
        service_name = f"MongoDB_{host}_{database}"
        
        try:
            if username and password:
                uri = f"mongodb://{username}:{password}@{host}:{port}/{database}"
            else:
                uri = f"mongodb://{host}:{port}/{database}"
            
            client = MongoClient(
                uri,
                serverSelectionTimeoutMS=timeout * 1000,
                socketTimeoutMS=timeout * 1000
            )
            
            # Проверка соединения
            client.admin.command('ping')
            
            # Получение информации о сервере
            server_info = client.server_info()
            
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.DATABASE,
                status=ServiceStatus.HEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                details={
                    "version": server_info.get('version'),
                    "host": server_info.get('host')
                }
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.DATABASE,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message=str(e)
            )


class APIChecker:
    """Проверка внешних API"""
    
    @staticmethod
    def check_http_service(url: str, method: str = 'GET',
                          headers: Optional[Dict] = None,
                          timeout: int = 5,
                          expected_status: int = 200) -> HealthCheckResult:
        """Проверка HTTP сервиса"""
        start_time = time.time()
        service_name = f"API_{url}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers or {},
                timeout=timeout,
                verify=True
            )
            
            response_time = (time.time() - start_time) * 1000
            
            if response.status_code == expected_status:
                return HealthCheckResult(
                    service_name=service_name,
                    service_type=ServiceType.API,
                    status=ServiceStatus.HEALTHY,
                    response_time=response_time,
                    timestamp=datetime.now(),
                    details={
                        "status_code": response.status_code,
                        "response_time_ms": response_time
                    }
                )
            else:
                return HealthCheckResult(
                    service_name=service_name,
                    service_type=ServiceType.API,
                    status=ServiceStatus.DEGRADED,
                    response_time=response_time,
                    timestamp=datetime.now(),
                    error_message=f"Unexpected status code: {response.status_code}",
                    details={"status_code": response.status_code}
                )
                
        except requests.exceptions.Timeout:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.API,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message="Request timeout"
            )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.API,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message=str(e)
            )
    
    @staticmethod
    def check_tcp_service(host: str, port: int, timeout: int) -> HealthCheckResult:
        """Проверка TCP соединения"""
        start_time = time.time()
        service_name = f"TCP_{host}:{port}"
        
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.EXTERNAL_SERVICE,
                status=ServiceStatus.HEALTHY,
                response_time=response_time,
                timestamp=datetime.now()
            )
            
        except socket.timeout:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.EXTERNAL_SERVICE,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message="Connection timeout"
            )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.EXTERNAL_SERVICE,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message=str(e)
            )
    
    @staticmethod
    def check_ssl_certificate(host: str, port: int = 443,
                             timeout: int = 5) -> HealthCheckResult:
        """Проверка SSL сертификата"""
        start_time = time.time()
        service_name = f"SSL_{host}:{port}"
        
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
                    
                    # Проверка срока действия
                    import datetime as dt
                    not_after = dt.datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
                    days_until_expiry = (not_after - dt.datetime.now()).days
                    
                    response_time = (time.time() - start_time) * 1000
                    
                    details = {
                        "issuer": dict(x[0] for x in cert['issuer']),
                        "subject": dict(x[0] for x in cert['subject']),
                        "not_after": cert['notAfter'],
                        "days_until_expiry": days_until_expiry
                    }
                    
                    status = ServiceStatus.HEALTHY
                    if days_until_expiry < 7:
                        status = ServiceStatus.DEGRADED
                    
                    return HealthCheckResult(
                        service_name=service_name,
                        service_type=ServiceType.EXTERNAL_SERVICE,
                        status=status,
                        response_time=response_time,
                        timestamp=datetime.now(),
                        details=details
                    )
                    
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_name=service_name,
                service_type=ServiceType.EXTERNAL_SERVICE,
                status=ServiceStatus.UNHEALTHY,
                response_time=response_time,
                timestamp=datetime.now(),
                error_message=str(e)
            )


class NotificationManager:
    """Менеджер уведомлений"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.last_notification_time = {}
        self.notification_cooldown = config.get('cooldown_minutes', 5)
    
    def send_email(self, subject: str, body: str, 
                  results: List[HealthCheckResult]) -> bool:
        """Отправка email уведомления"""
        try:
            smtp_config = self.config.get('smtp', {})
            
            msg = MIMEMultipart()
            msg['From'] = smtp_config.get('from_email')
            msg['To'] = ', '.join(smtp_config.get('recipients', []))
            msg['Subject'] = subject
            
            # Формирование HTML отчета
            html = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    table {{ border-collapse: collapse; width: 100%; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    th {{ background-color: #f2f2f2; }}
                    .healthy {{ background-color: #d4edda; }}
                    .unhealthy {{ background-color: #f8d7da; }}
                    .degraded {{ background-color: #fff3cd; }}
                </style>
            </head>
            <body>
                <h2>Health Check Report</h2>
                <p>{body}</p>
                <p>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <table>
                    <tr>
                        <th>Service</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Response Time (ms)</th>
                        <th>Error</th>
                        <th>Time</th>
                    </tr>
            """
            
            for result in results:
                status_class = result.status.value.lower()
                html += f"""
                    <tr class="{status_class}">
                        <td>{result.service_name}</td>
                        <td>{result.service_type.value}</td>
                        <td>{result.status.value}</td>
                        <td>{result.response_time:.2f}</td>
                        <td>{result.error_message or '-'}</td>
                        <td>{result.timestamp.strftime('%H:%M:%S')}</td>
                    </tr>
                """
            
            html += """
                </table>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            with smtplib.SMTP(smtp_config.get('host'), smtp_config.get('port')) as server:
                if smtp_config.get('use_tls'):
                    server.starttls()
                if smtp_config.get('username'):
                    server.login(smtp_config.get('username'), 
                                smtp_config.get('password'))
                server.send_message(msg)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    def send_slack(self, message: str, results: List[HealthCheckResult]) -> bool:
        """Отправка уведомления в Slack"""
        try:
            webhook_url = self.config.get('slack', {}).get('webhook_url')
            if not webhook_url:
                return False
            
            unhealthy_services = [
                r for r in results 
                if r.status in [ServiceStatus.UNHEALTHY, ServiceStatus.DEGRADED]
            ]
            
            attachments = []
            for result in unhealthy_services:
                color = "danger" if result.status == ServiceStatus.UNHEALTHY else "warning"
                attachments.append({
                    "color": color,
                    "title": f"{result.service_name} - {result.service_type.value}",
                    "fields": [
                        {"title": "Status", "value": result.status.value, "short": True},
                        {"title": "Response Time", "value": f"{result.response_time:.2f}ms", "short": True},
                        {"title": "Error", "value": result.error_message or "No error", "short": False}
                    ],
                    "ts": int(result.timestamp.timestamp())
                })
            
            payload = {
                "text": message,
                "attachments": attachments,
                "mrkdwn": True
            }
            
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=5
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False
    
    def should_send_notification(self, service_name: str) -> bool:
        """Проверка, нужно ли отправлять уведомление (для избежания спама)"""
        current_time = time.time()
        last_time = self.last_notification_time.get(service_name, 0)
        
        if current_time - last_time > self.notification_cooldown * 60:
            self.last_notification_time[service_name] = current_time
            return True
        return False


class HealthMonitor:
    """Основной класс мониторинга здоровья"""
    
    def __init__(self, config_file: str = "health_monitor_config.json"):
        self.services: List[ServiceConfig] = []
        self.results_history: List[HealthCheckResult] = []
        self.max_history_size = 1000
        self.is_running = False
        self.thread_pool = ThreadPoolExecutor(max_workers=10)
        self.notification_manager = None
        
        self.load_config(config_file)
        
        # Регистрация проверок
        self.check_registry = {
            ServiceType.DATABASE: self.check_database,
            ServiceType.API: self.check_api,
            ServiceType.CACHE: self.check_cache,
            ServiceType.EXTERNAL_SERVICE: self.check_external_service
        }
    
    def load_config(self, config_file: str):
        """Загрузка конфигурации из файла"""
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            # Загрузка сервисов
            for service_config in config.get('services', []):
                service = ServiceConfig(
                    name=service_config['name'],
                    service_type=ServiceType(service_config['type']),
                    check_interval=service_config['check_interval'],
                    timeout=service_config.get('timeout', 5),
                    enabled=service_config.get('enabled', True),
                    params=service_config.get('params', {})
                )
                self.services.append(service)
            
            # Настройка уведомлений
            if 'notifications' in config:
                self.notification_manager = NotificationManager(
                    config['notifications']
                )
            
            logger.info(f"Loaded configuration from {config_file}")
            
        except FileNotFoundError:
            logger.warning(f"Config file {config_file} not found, using defaults")
            self.create_default_config(config_file)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
    
    def create_default_config(self, config_file: str):
        """Создание конфигурации по умолчанию"""
        default_config = {
            "services": [
                {
                    "name": "example_database",
                    "type": "DATABASE",
                    "check_interval": 60,
                    "timeout": 5,
                    "enabled": False,
                    "params": {
                        "type": "mysql",
                        "host": "localhost",
                        "port": 3306,
                        "database": "test",
                        "username": "user",
                        "password": "password"
                    }
                }
            ],
            "notifications": {
                "enabled": False,
                "cooldown_minutes": 5,
                "smtp": {
                    "host": "smtp.gmail.com",
                    "port": 587,
                    "use_tls": True,
                    "from_email": "monitor@example.com",
                    "recipients": ["admin@example.com"]
                }
            }
        }
        
        with open(config_file, 'w') as f:
            json.dump(default_config, f, indent=2)
        
        logger.info(f"Created default configuration in {config_file}")
    
    def check_database(self, service_config: ServiceConfig) -> HealthCheckResult:
        """Проверка базы данных"""
        params = service_config.params
        db_type = params.get('type', '').lower()
        
        if db_type == 'mysql':
            return DatabaseChecker.check_mysql(
                host=params['host'],
                port=params.get('port', 3306),
                user=params['username'],
                password=params['password'],
                database=params['database'],
                timeout=service_config.timeout
            )
        elif db_type == 'postgresql':
            return DatabaseChecker.check_postgresql(
                host=params['host'],
                port=params.get('port', 5432),
                user=params['username'],
                password=params['password'],
                database=params['database'],
                timeout=service_config.timeout
            )
        elif db_type == 'mongodb':
            return DatabaseChecker.check_mongodb(
                host=params['host'],
                port=params.get('port', 27017),
                username=params.get('username'),
                password=params.get('password'),
                database=params['database'],
                timeout=service_config.timeout
            )
        else:
            return HealthCheckResult(
                service_name=service_config.name,
                service_type=service_config.service_type,
                status=ServiceStatus.UNKNOWN,
                response_time=0,
                timestamp=datetime.now(),
                error_message=f"Unsupported database type: {db_type}"
            )
    
    def check_api(self, service_config: ServiceConfig) -> HealthCheckResult:
        """Проверка API"""
        params = service_config.params
        
        if params.get('check_type') == 'tcp':
            return APIChecker.check_tcp_service(
                host=params['host'],
                port=params['port'],
                timeout=service_config.timeout
            )
        elif params.get('check_type') == 'ssl':
            return APIChecker.check_ssl_certificate(
                host=params['host'],
                port=params.get('port', 443),
                timeout=service_config.timeout
            )
        else:
            return APIChecker.check_http_service(
                url=params['url'],
                method=params.get('method', 'GET'),
                headers=params.get('headers'),
                timeout=service_config.timeout,
                expected_status=params.get('expected_status', 200)
            )
    
    def check_cache(self, service_config: ServiceConfig) -> HealthCheckResult:
        """Проверка кэша"""
        params = service_config.params
        cache_type = params.get('type', '').lower()
        
        if cache_type == 'redis':
            return DatabaseChecker.check_redis(
                host=params['host'],
                port=params.get('port', 6379),
                password=params.get('password'),
                timeout=service_config.timeout
            )
        else:
            return HealthCheckResult(
                service_name=service_config.name,
                service_type=service_config.service_type,
                status=ServiceStatus.UNKNOWN,
                response_time=0,
                timestamp=datetime.now(),
                error_message=f"Unsupported cache type: {cache_type}"
            )
    
    def check_external_service(self, service_config: ServiceConfig) -> HealthCheckResult:
        """Проверка внешнего сервиса"""
        params = service_config.params
        check_type = params.get('check_type', 'http')
        
        if check_type == 'tcp':
            return APIChecker.check_tcp_service(
                host=params['host'],
                port=params['port'],
                timeout=service_config.timeout
            )
        elif check_type == 'ssl':
            return APIChecker.check_ssl_certificate(
                host=params['host'],
                port=params.get('port', 443),
                timeout=service_config.timeout
            )
        else:
            return APIChecker.check_http_service(
                url=params['url'],
                method=params.get('method', 'GET'),
                headers=params.get('headers'),
                timeout=service_config.timeout,
                expected_status=params.get('expected_status', 200)
            )
    
    def check_service(self, service_config: ServiceConfig) -> HealthCheckResult:
        """Выполнение проверки сервиса"""
        try:
            if not service_config.enabled:
                return HealthCheckResult(
                    service_name=service_config.name,
                    service_type=service_config.service_type,
                    status=ServiceStatus.UNKNOWN,
                    response_time=0,
                    timestamp=datetime.now(),
                    error_message="Service check disabled"
                )
            
            checker = self.check_registry.get(service_config.service_type)
            if checker:
                return checker(service_config)
            else:
                return HealthCheckResult(
                    service_name=service_config.name,
                    service_type=service_config.service_type,
                    status=ServiceStatus.UNKNOWN,
                    response_time=0,
                    timestamp=datetime.now(),
                    error_message=f"No checker for type {service_config.service_type}"
                )
                
        except Exception as e:
            logger.error(f"Error checking service {service_config.name}: {e}")
            return HealthCheckResult(
                service_name=service_config.name,
                service_type=service_config.service_type,
                status=ServiceStatus.UNHEALTHY,
                response_time=0,
                timestamp=datetime.now(),
                error_message=str(e)
            )
    
    def run_all_checks(self) -> List[HealthCheckResult]:
        """Запуск всех проверок параллельно"""
        futures = {}
        results = []
        
        for service in self.services:
            future = self.thread_pool.submit(self.check_service, service)
            futures[future] = service.name
        
        for future in as_completed(futures):
            try:
                result = future.result(timeout=30)
                results.append(result)
                
                # Логирование результата
                if result.status == ServiceStatus.HEALTHY:
                    logger.info(
                        f"Service {result.service_name} is healthy. "
                        f"Response time: {result.response_time:.2f}ms"
                    )
                else:
                    logger.warning(
                        f"Service {result.service_name} is {result.status.value}. "
                        f"Error: {result.error_message}"
                    )
                
                # Сохранение в историю
                self.results_history.append(result)
                if len(self.results_history) > self.max_history_size:
                    self.results_history.pop(0)
                
                # Отправка уведомления при проблемах
                if (result.status in [ServiceStatus.UNHEALTHY, ServiceStatus.DEGRADED] and 
                    self.notification_manager and
                    self.notification_manager.should_send_notification(result.service_name)):
                    
                    self.notification_manager.send_email(
                        subject=f"Health Alert: {result.service_name} is {result.status.value}",
                        body=f"Service {result.service_name} is experiencing issues.",
                        results=[result]
                    )
                    
            except Exception as e:
                logger.error(f"Error processing check result: {e}")
        
        return results
    
    def schedule_checks(self):
        """Планирование периодических проверок"""
        for service in self.services:
            schedule.every(service.check_interval).seconds.do(
                self.run_scheduled_check, service
            )
        
        logger.info(f"Scheduled {len(self.services)} health checks")
    
    def run_scheduled_check(self, service: ServiceConfig):
        """Запуск запланированной проверки"""
        result = self.check_service(service)
        
        # Логирование результата
        if result.status == ServiceStatus.HEALTHY:
            logger.info(
                f"Scheduled check: {result.service_name} is healthy. "
                f"Response time: {result.response_time:.2f}ms"
            )
        else:
            logger.warning(
                f"Scheduled check: {result.service_name} is {result.status.value}. "
                f"Error: {result.error_message}"
            )
    
    def generate_report(self) -> Dict:
        """Генерация отчета о состоянии системы"""
        if not self.results_history:
            return {"status": "NO_DATA", "services": []}
        
        # Последние результаты для каждого сервиса
        latest_results = {}
        for result in reversed(self.results_history):
            if result.service_name not in latest_results:
                latest_results[result.service_name] = result
        
        # Статистика
        total_services = len(latest_results)
        healthy_services = sum(
            1 for r in latest_results.values() 
            if r.status == ServiceStatus.HEALTHY
        )
        unhealthy_services = sum(
            1 for r in latest_results.values() 
            if r.status == ServiceStatus.UNHEALTHY
        )
        
        overall_status = ServiceStatus.HEALTHY
        if unhealthy_services > 0:
            overall_status = ServiceStatus.UNHEALTHY
        elif total_services - healthy_services > 0:
            overall_status = ServiceStatus.DEGRADED
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": overall_status.value,
            "statistics": {
                "total_services": total_services,
                "healthy_services": healthy_services,
                "unhealthy_services": unhealthy_services,
                "degraded_services": total_services - healthy_services - unhealthy_services
            },
            "services": []
        }
        
        for result in latest_results.values():
            service_report = {
                "name": result.service_name,
                "type": result.service_type.value,
                "status": result.status.value,
                "response_time_ms": result.response_time,
                "last_check": result.timestamp.isoformat(),
                "error": result.error_message
            }
            report["services"].append(service_report)
        
        return report
    
    def start(self):
        """Запуск мониторинга"""
        if self.is_running:
            logger.warning("Monitor is already running")
            return
        
        self.is_running = True
        self.schedule_checks()
        
        logger.info("Health monitor started")
        
        # Основной цикл
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Shutting down health monitor...")
                self.stop()
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)
    
    def stop(self):
        """Остановка мониторинга"""
        self.is_running = False
        self.thread_pool.shutdown(wait=True)
        logger.info("Health monitor stopped")
    
    def run_once(self):
        """Однократный запуск всех проверок"""
        logger.info("Running one-time health check...")
        results = self.run_all_checks()
        
        # Вывод отчета в консоль
        print("\n" + "="*80)
        print("HEALTH CHECK REPORT")
        print("="*80)
        
        for result in results:
            status_icon = "✓" if result.status == ServiceStatus.HEALTHY else "✗"
            print(f"{status_icon} {result.service_name:30} {result.status.value:15} "
                  f"{result.response_time:6.2f}ms")
            if result.error_message:
                print(f"   Error: {result.error_message}")
        
        print("="*80)
        
        # Сохранение отчета в файл
        report = self.generate_report()
        with open('health_report.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        return results


def main():
    """Точка входа в программу"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Health Monitoring System')
    parser.add_argument('--config', default='health_monitor_config.json',
                       help='Configuration file path')
    parser.add_argument('--once', action='store_true',
                       help='Run checks once and exit')
    parser.add_argument('--report', action='store_true',
                       help='Generate report from last results')
    
    args = parser.parse_args()
    
    monitor = HealthMonitor(args.config)
    
    if args.once:
        monitor.run_once()
    elif args.report:
        report = monitor.generate_report()
        print(json.dumps(report, indent=2))
    else:
        try:
            monitor.start()
        except KeyboardInterrupt:
            monitor.stop()


if __name__ == "__main__":
    main()