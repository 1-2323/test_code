import logging
import json
import re
import time
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, Callable
from functools import wraps
import hashlib
import ipaddress

class PIIScrubber:
    """Класс для очистки PII данных из логов"""
    
    # Регулярные выражения для обнаружения PII
    PATTERNS = {
        'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        'phone': re.compile(r'\b(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b'),
        'ipv4': re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'),
        'credit_card': re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'),
    }
    
    @staticmethod
    def mask_email(email: str) -> str:
        """Маскирует email адрес"""
        if '@' not in email:
            return email
        local_part, domain = email.split('@', 1)
        if len(local_part) <= 2:
            masked_local = '*' * len(local_part)
        else:
            masked_local = local_part[0] + '*' * (len(local_part) - 2) + local_part[-1]
        return f"{masked_local}@{domain}"
    
    @staticmethod
    def mask_phone(phone: str) -> str:
        """Маскирует номер телефона"""
        digits = re.sub(r'\D', '', phone)
        if len(digits) >= 10:
            return f"{digits[:3]}***{digits[-4:]}"
        return "***"
    
    @staticmethod
    def anonymize_ip(ip: str) -> str:
        """Анонимизирует IP адрес (сохраняет только префикс)"""
        try:
            ip_obj = ipaddress.ip_address(ip)
            if isinstance(ip_obj, ipaddress.IPv4Address):
                # Для IPv4: сохраняем первые 2 октета
                parts = str(ip_obj).split('.')
                return f"{parts[0]}.{parts[1]}.0.0"
            else:
                # Для IPv6: сохраняем первые 64 бита
                return f"{ip_obj.exploded[:19]}::"
        except ValueError:
            return "0.0.0.0"
    
    @classmethod
    def scrub_string(cls, text: str) -> str:
        """Очищает строку от PII данных"""
        scrubbed = text
        
        # Маскируем email
        for match in cls.PATTERNS['email'].finditer(scrubbed):
            email = match.group()
            scrubbed = scrubbed.replace(email, cls.mask_email(email))
        
        # Маскируем телефоны
        for match in cls.PATTERNS['phone'].finditer(scrubbed):
            phone = match.group()
            scrubbed = scrubbed.replace(phone, cls.mask_phone(phone))
        
        # Маскируем IP адреса
        for match in cls.PATTERNS['ipv4'].finditer(scrubbed):
            ip = match.group()
            scrubbed = scrubbed.replace(ip, cls.anonymize_ip(ip))
        
        # Маскируем номера кредитных карт
        for match in cls.PATTERNS['credit_card'].finditer(scrubbed):
            card = match.group()
            digits = re.sub(r'\D', '', card)
            if len(digits) == 16:
                masked = digits[:6] + '*' * 6 + digits[-4:]
                scrubbed = scrubbed.replace(card, masked)
        
        return scrubbed
    
    @classmethod
    def scrub_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Рекурсивно очищает словарь от PII данных"""
        scrubbed = {}
        sensitive_keys = {'password', 'passwd', 'secret', 'token', 'key', 'auth', 'credential'}
        
        for key, value in data.items():
            # Пропускаем чувствительные ключи
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                scrubbed[key] = '[REDACTED]'
                continue
            
            if isinstance(value, str):
                scrubbed[key] = cls.scrub_string(value)
            elif isinstance(value, dict):
                scrubbed[key] = cls.scrub_dict(value)
            elif isinstance(value, list):
                scrubbed[key] = [cls.scrub_dict(item) if isinstance(item, dict) 
                               else cls.scrub_string(item) if isinstance(item, str) 
                               else item for item in value]
            else:
                scrubbed[key] = value
        
        return scrubbed


class AuthLogger:
    """Класс для логирования событий аутентификации"""
    
    def __init__(self, logger_name: str = 'auth_logger', log_level: int = logging.INFO):
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(log_level)
        self.scrubber = PIIScrubber()
        
        # Настраиваем обработчик, если его еще нет
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def _prepare_log_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Подготовка данных для логирования с очисткой PII"""
        scrubbed_data = self.scrubber.scrub_dict(data.copy())
        
        # Хэшируем идентификаторы для связности логов без раскрытия PII
        if 'user_id' in scrubbed_data:
            user_hash = hashlib.sha256(
                str(scrubbed_data['user_id']).encode()
            ).hexdigest()[:16]
            scrubbed_data['user_hash'] = user_hash
            del scrubbed_data['user_id']
        
        if 'username' in scrubbed_data:
            username_hash = hashlib.sha256(
                str(scrubbed_data['username']).encode()
            ).hexdigest()[:16]
            scrubbed_data['username_hash'] = username_hash
            del scrubbed_data['username']
        
        # Удаляем временные метки если они есть, добавляем свои
        if 'timestamp' in scrubbed_data:
            del scrubbed_data['timestamp']
        
        scrubbed_data['log_timestamp'] = datetime.utcnow().isoformat() + 'Z'
        
        return scrubbed_data
    
    def log_success(self, request_data: Dict[str, Any], additional_info: Dict[str, Any] = None):
        """Логирование успешного входа"""
        log_data = self._prepare_log_data(request_data)
        log_data['event_type'] = 'auth_success'
        
        if additional_info:
            log_data.update(self.scrubber.scrub_dict(additional_info))
        
        self.logger.info(
            "Successful authentication",
            extra={'log_data': json.dumps(log_data, ensure_ascii=False)}
        )
    
    def log_failure(self, request_data: Dict[str, Any], failure_reason: str, 
                   additional_info: Dict[str, Any] = None):
        """Логирование неудачной попытки входа"""
        log_data = self._prepare_log_data(request_data)
        log_data['event_type'] = 'auth_failure'
        log_data['failure_reason'] = failure_reason
        
        if additional_info:
            log_data.update(self.scrubber.scrub_dict(additional_info))
        
        self.logger.warning(
            f"Failed authentication attempt: {failure_reason}",
            extra={'log_data': json.dumps(log_data, ensure_ascii=False)}
        )
    
    def log_logout(self, request_data: Dict[str, Any]):
        """Логирование выхода из системы"""
        log_data = self._prepare_log_data(request_data)
        log_data['event_type'] = 'logout'
        
        self.logger.info(
            "User logged out",
            extra={'log_data': json.dumps(log_data, ensure_ascii=False)}
        )


def auth_logging_middleware(auth_logger: AuthLogger):
    """
    Middleware для логирования событий аутентификации
    
    Args:
        auth_logger: Экземпляр AuthLogger для логирования
    """
    def decorator(handler: Callable) -> Callable:
        @wraps(handler)
        async def async_wrapper(request, *args, **kwargs):
            return await _process_request(handler, request, *args, **kwargs)
        
        @wraps(handler)
        def sync_wrapper(request, *args, **kwargs):
            return _process_request(handler, request, *args, **kwargs)
        
        def _process_request(handler, request, *args, **kwargs):
            start_time = time.time()
            
            # Собираем базовую информацию о запросе
            request_data = {
                'endpoint': getattr(request, 'path', str(request)),
                'method': getattr(request, 'method', 'UNKNOWN'),
                'user_agent': request.headers.get('User-Agent', 'Unknown'),
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
            
            # Извлекаем IP адрес с учетом прокси
            x_forwarded_for = request.headers.get('X-Forwarded-For')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.remote_addr if hasattr(request, 'remote_addr') else '0.0.0.0'
            request_data['ip_address'] = ip
            
            try:
                # Получаем данные аутентификации из запроса
                auth_data = _extract_auth_data(request)
                if auth_data:
                    request_data.update(auth_data)
                
                # Выполняем обработчик
                response = handler(request, *args, **kwargs)
                
                # Определяем тип события на основе ответа
                if _is_successful_auth(response):
                    auth_logger.log_success(request_data)
                elif _is_auth_endpoint(request):
                    failure_reason = _get_failure_reason(response)
                    auth_logger.log_failure(request_data, failure_reason)
                
                return response
                
            except Exception as e:
                # Логируем исключения при аутентификации
                if _is_auth_endpoint(request):
                    auth_logger.log_failure(
                        request_data, 
                        f"Authentication error: {str(e)}"
                    )
                raise
            
            finally:
                # Логируем время выполнения
                processing_time = time.time() - start_time
                if processing_time > 1.0:  # Логируем только медленные запросы
                    slow_log_data = request_data.copy()
                    slow_log_data['processing_time'] = processing_time
                    auth_logger.logger.warning(
                        f"Slow authentication request: {processing_time:.2f}s",
                        extra={'log_data': json.dumps(
                            auth_logger.scrubber.scrub_dict(slow_log_data),
                            ensure_ascii=False
                        )}
                    )
        
        # Возвращаем правильную обертку в зависимости от типа handler
        import asyncio
        if asyncio.iscoroutinefunction(handler):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def _extract_auth_data(request) -> Optional[Dict[str, Any]]:
    """Извлекает данные аутентификации из запроса"""
    auth_data = {}
    
    # Проверяем заголовок Authorization
    auth_header = request.headers.get('Authorization')
    if auth_header:
        auth_data['auth_method'] = 'bearer' if 'Bearer' in auth_header else 'other'
    
    # Проверяем данные формы/JSON
    try:
        if hasattr(request, 'json'):
            body = request.json
            if body and isinstance(body, dict):
                if 'username' in body:
                    auth_data['username'] = body['username']
                if 'email' in body:
                    auth_data['email'] = body['email']
    except:
        pass
    
    return auth_data if auth_data else None


def _is_auth_endpoint(request) -> bool:
    """Определяет, является ли endpoint аутентификационным"""
    auth_paths = {'/login', '/auth', '/signin', '/token', '/oauth'}
    path = getattr(request, 'path', str(request)).lower()
    return any(auth_path in path for auth_path in auth_paths)


def _is_successful_auth(response) -> bool:
    """Определяет, была ли аутентификация успешной"""
    if hasattr(response, 'status_code'):
        return response.status_code == 200
    return False


def _get_failure_reason(response) -> str:
    """Извлекает причину неудачи из ответа"""
    if hasattr(response, 'status_code'):
        if response.status_code == 401:
            return "Invalid credentials"
        elif response.status_code == 403:
            return "Access denied"
        elif response.status_code == 429:
            return "Too many attempts"
    return "Authentication failed"


# Пример настройки и использования (не для выполнения, только для демонстрации структуры)
if __name__ == "__main__":
    # Инициализация логгера
    logger = AuthLogger(log_level=logging.INFO)
    
    # Настройка дополнительного файлового обработчика
    file_handler = logging.FileHandler('auth_audit.log')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.logger.addHandler(file_handler)