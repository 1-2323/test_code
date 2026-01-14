import logging
import time
from typing import Callable, Optional
from datetime import datetime
import json
from functools import wraps
from flask import request, g
from werkzeug.local import LocalProxy

# Настройка логгера
logger = logging.getLogger('auth_logger')
logger.setLevel(logging.INFO)

# Форматирование логов
formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Обработчик для записи в файл
file_handler = logging.FileHandler('auth_events.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Обработчик для консоли (опционально)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Локальный прокси для доступа к данным аутентификации
auth_data: LocalProxy = LocalProxy(lambda: getattr(g, '_auth_data', {}))

class AuthLogger:
    """Класс для управления логированием аутентификации"""
    
    @staticmethod
    def log_successful_login(
        user_id: str,
        username: str,
        ip_address: str,
        user_agent: str,
        additional_info: Optional[dict] = None
    ) -> None:
        """Логирование успешного входа"""
        log_data = {
            'event_type': 'LOGIN_SUCCESS',
            'timestamp': datetime.utcnow().isoformat(),
            'user_id': user_id,
            'username': username,
            'ip_address': ip_address,
            'user_agent': user_agent,
            'status': 'SUCCESS'
        }
        
        if additional_info:
            log_data.update(additional_info)
            
        logger.info(
            f"Successful login - User: {username} (ID: {user_id}) "
            f"from IP: {ip_address}",
            extra={'log_data': log_data}
        )
    
    @staticmethod
    def log_failed_attempt(
        username: Optional[str],
        ip_address: str,
        failure_reason: str,
        user_agent: str,
        attempt_count: int = 1,
        additional_info: Optional[dict] = None
    ) -> None:
        """Логирование неудачной попытки входа"""
        log_data = {
            'event_type': 'LOGIN_FAILURE',
            'timestamp': datetime.utcnow().isoformat(),
            'username_attempted': username,
            'ip_address': ip_address,
            'user_agent': user_agent,
            'failure_reason': failure_reason,
            'attempt_count': attempt_count,
            'status': 'FAILURE'
        }
        
        if additional_info:
            log_data.update(additional_info)
            
        logger.warning(
            f"Failed login attempt - Username: {username or 'N/A'} "
            f"from IP: {ip_address}, Reason: {failure_reason}, "
            f"Attempt: {attempt_count}",
            extra={'log_data': log_data}
        )
    
    @staticmethod
    def log_logout(
        user_id: str,
        username: str,
        ip_address: str,
        session_duration: float,
        additional_info: Optional[dict] = None
    ) -> None:
        """Логирование выхода из системы"""
        log_data = {
            'event_type': 'LOGOUT',
            'timestamp': datetime.utcnow().isoformat(),
            'user_id': user_id,
            'username': username,
            'ip_address': ip_address,
            'session_duration_seconds': round(session_duration, 2),
            'status': 'LOGGED_OUT'
        }
        
        if additional_info:
            log_data.update(additional_info)
            
        logger.info(
            f"User logout - User: {username} (ID: {user_id}), "
            f"Session duration: {session_duration:.2f}s",
            extra={'log_data': log_data}
        )
    
    @staticmethod
    def log_account_lockout(
        username: str,
        ip_address: str,
        lockout_reason: str,
        lockout_duration: Optional[int] = None,
        additional_info: Optional[dict] = None
    ) -> None:
        """Логирование блокировки аккаунта"""
        log_data = {
            'event_type': 'ACCOUNT_LOCKOUT',
            'timestamp': datetime.utcnow().isoformat(),
            'username': username,
            'ip_address': ip_address,
            'lockout_reason': lockout_reason,
            'lockout_duration_minutes': lockout_duration,
            'status': 'LOCKED'
        }
        
        if additional_info:
            log_data.update(additional_info)
            
        logger.error(
            f"Account lockout - User: {username} from IP: {ip_address}, "
            f"Reason: {lockout_reason}",
            extra={'log_data': log_data}
        )


class JSONFormatter(logging.Formatter):
    """Кастомный форматтер для JSON логов"""
    
    def format(self, record):
        log_record = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
        }
        
        # Добавляем дополнительные данные из extra
        if hasattr(record, 'log_data'):
            log_record['data'] = record.log_data
        
        # Добавляем информацию об исключении, если есть
        if record.exc_info:
            log_record['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_record, ensure_ascii=False)


class AuthLoggingMiddleware:
    """Middleware для логирования событий аутентификации"""
    
    def __init__(self, app=None, logger_instance: Optional[AuthLogger] = None):
        self.app = app
        self.logger = logger_instance or AuthLogger()
        self.failed_attempts = {}
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """Инициализация middleware с приложением"""
        app.before_request(self._before_request)
        app.after_request(self._after_request)
        
        # Настройка JSON логгера
        json_handler = logging.FileHandler('auth_events.json')
        json_handler.setFormatter(JSONFormatter())
        logger.addHandler(json_handler)
    
    def _before_request(self):
        """Выполняется перед каждым запросом"""
        g._auth_data = {
            'login_time': time.time(),
            'ip_address': request.remote_addr,
            'user_agent': request.user_agent.string
        }
    
    def _after_request(self, response):
        """Выполняется после каждого запроса"""
        # Очистка данных аутентификации из контекста
        if hasattr(g, '_auth_data'):
            del g._auth_data
        
        return response
    
    def track_failed_attempt(self, username: str, ip_address: str) -> int:
        """Отслеживание количества неудачных попыток"""
        key = f"{username}::{ip_address}"
        
        if key not in self.failed_attempts:
            self.failed_attempts[key] = {
                'count': 0,
                'first_attempt': time.time(),
                'last_attempt': time.time()
            }
        
        self.failed_attempts[key]['count'] += 1
        self.failed_attempts[key]['last_attempt'] = time.time()
        
        # Очистка старых записей (старше 1 часа)
        self._cleanup_old_attempts()
        
        return self.failed_attempts[key]['count']
    
    def reset_failed_attempts(self, username: str, ip_address: str) -> None:
        """Сброс счетчика неудачных попыток"""
        key = f"{username}::{ip_address}"
        if key in self.failed_attempts:
            del self.failed_attempts[key]
    
    def get_failed_attempts_count(self, username: str, ip_address: str) -> int:
        """Получение количества неудачных попыток"""
        key = f"{username}::{ip_address}"
        if key in self.failed_attempts:
            return self.failed_attempts[key]['count']
        return 0
    
    def _cleanup_old_attempts(self, max_age: int = 3600):
        """Очистка устаревших записей о попытках"""
        current_time = time.time()
        keys_to_delete = []
        
        for key, data in self.failed_attempts.items():
            if current_time - data['last_attempt'] > max_age:
                keys_to_delete.append(key)
        
        for key in keys_to_delete:
            del self.failed_attempts[key]


def require_auth_logging(f: Callable) -> Callable:
    """
    Декоратор для логирования аутентификации в функциях/методах
    
    Использование:
        @require_auth_logging
        def login_user(username, password):
            # логика аутентификации
            pass
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        result = None
        error = None
        
        try:
            result = f(*args, **kwargs)
            return result
        except Exception as e:
            error = str(e)
            raise
        finally:
            # Логирование можно добавить здесь при необходимости
            pass
    
    return decorated_function


# Дополнительные утилиты для удобства использования
def setup_auth_logging(app, config_prefix='AUTH_LOGGING'):
    """
    Настройка логирования аутентификации для приложения
    
    Пример использования:
        app = Flask(__name__)
        auth_middleware = setup_auth_logging(app)
    """
    middleware = AuthLoggingMiddleware(app)
    
    # Конфигурация из настроек приложения
    log_level = app.config.get(f'{config_prefix}_LEVEL', 'INFO')
    log_file = app.config.get(f'{config_prefix}_FILE', 'auth_events.log')
    json_log_file = app.config.get(f'{config_prefix}_JSON_FILE', 'auth_events.json')
    
    # Обновление обработчиков
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Файловый обработчик
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # JSON обработчик
    json_handler = logging.FileHandler(json_log_file)
    json_handler.setFormatter(JSONFormatter())
    logger.addHandler(json_handler)
    
    # Консольный обработчик (если включен в конфигурации)
    if app.config.get(f'{config_prefix}_CONSOLE', False):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # Уровень логирования
    logger.setLevel(getattr(logging, log_level.upper()))
    
    return middleware


# Экспорт основных компонентов
__all__ = [
    'AuthLogger',
    'AuthLoggingMiddleware',
    'require_auth_logging',
    'setup_auth_logging',
    'logger'
]