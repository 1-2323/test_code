import logging
import re
from typing import Dict, Any, Callable
from datetime import datetime

class HeadersLoggingMiddleware:
    """Middleware для логирования заголовков HTTP-запросов"""
    
    def __init__(self, app: Callable, log_file: str = 'headers.log'):
        """
        Инициализация middleware
        
        Args:
            app: WSGI приложение
            log_file: путь к файлу лога
        """
        self.app = app
        self.log_file = log_file
        
        # Настройка логгера
        self.logger = logging.getLogger('headers_logger')
        self.logger.setLevel(logging.INFO)
        
        # Обработчик для записи в файл
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # Форматтер лога
        formatter = logging.Formatter(
            '%(asctime)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        # Удаляем существующие обработчики, чтобы избежать дублирования
        self.logger.handlers.clear()
        self.logger.addHandler(file_handler)
        self.logger.propagate = False
    
    def _sanitize_string(self, value: str) -> str:
        """
        Очистка строки от символов новой строки для предотвращения Log Injection
        
        Args:
            value: строка для очистки
            
        Returns:
            Очищенная строка
        """
        if not isinstance(value, str):
            return str(value)
        
        # Удаляем \n, \r и табуляции
        sanitized = re.sub(r'[\n\r\t]', ' ', value)
        # Удаляем лишние пробелы
        sanitized = re.sub(r'\s+', ' ', sanitized).strip()
        
        return sanitized
    
    def _extract_headers(self, environ: Dict[str, Any]) -> Dict[str, str]:
        """
        Извлечение и очистка заголовков из environ
        
        Args:
            environ: WSGI environ словарь
            
        Returns:
            Словарь с очищенными заголовками
        """
        headers = {}
        
        # Преобразуем все ключи environ в HTTP-заголовки
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                # Преобразуем HTTP_USER_AGENT в User-Agent
                header_name = key[5:].replace('_', '-').title()
                headers[header_name] = self._sanitize_string(value)
        
        # Добавляем Content-Type и Content-Length, если они есть
        for key in ['CONTENT_TYPE', 'CONTENT_LENGTH']:
            if key in environ:
                header_name = key.replace('_', '-').title()
                headers[header_name] = self._sanitize_string(environ[key])
        
        # Добавляем метод запроса и путь
        headers['Request-Method'] = self._sanitize_string(environ.get('REQUEST_METHOD', ''))
        headers['Request-Path'] = self._sanitize_string(environ.get('PATH_INFO', ''))
        
        return headers
    
    def __call__(self, environ: Dict[str, Any], start_response: Callable) -> Any:
        """
        Обработка WSGI запроса
        
        Args:
            environ: WSGI environ словарь
            start_response: функция start_response
            
        Returns:
            Ответ приложения
        """
        # Извлекаем и логируем заголовки
        headers = self._extract_headers(environ)
        
        # Формируем запись лога
        log_entries = []
        log_entries.append(f"Request: {headers.get('Request-Method', '')} {headers.get('Request-Path', '')}")
        
        # Логируем User-Agent отдельной строкой
        if 'User-Agent' in headers:
            log_entries.append(f"User-Agent: {headers['User-Agent']}")
        
        # Логируем другие важные заголовки
        important_headers = ['X-Forwarded-For', 'X-Real-Ip', 'Referer', 'Accept-Language', 'Host']
        for header in important_headers:
            if header in headers:
                log_entries.append(f"{header}: {headers[header]}")
        
        # Записываем в лог
        for entry in log_entries:
            self.logger.info(entry)
        
        # Пропускаем запрос дальше по цепочке middleware
        return self.app(environ, start_response)