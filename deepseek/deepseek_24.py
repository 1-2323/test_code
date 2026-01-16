# app/middleware/security_headers.py
from typing import Callable, Dict
from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware для добавления защитных HTTP-заголовков ко всем ответам
    """
    
    def __init__(self, app: FastAPI):
        super().__init__(app)
        self.security_headers = self._get_default_headers()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Обработка запроса и добавление заголовков безопасности
        
        Args:
            request: Входящий HTTP запрос
            call_next: Следующий middleware/обработчик
            
        Returns:
            HTTP ответ с добавленными заголовками безопасности
        """
        response = await call_next(request)
        
        # Добавляем заголовки к ответу
        for header, value in self.security_headers.items():
            response.headers[header] = value
        
        return response
    
    def _get_default_headers(self) -> Dict[str, str]:
        """
        Возвращает словарь с заголовками безопасности по умолчанию
        
        Returns:
            Словарь заголовок->значение
        """
        return {
            # Защита от межсайтового скриптинга (XSS)
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: https:; "
                "connect-src 'self' https://api.example.com;"
            ),
            
            # Защита от подмены типа контента (MIME sniffing)
            "X-Content-Type-Options": "nosniff",
            
            # Защита от кликджекинга
            "X-Frame-Options": "DENY",
            
            # Политика реферера
            "Referrer-Policy": "strict-origin-when-cross-origin",
            
            # Запрет использования опасных функций браузера
            "Permissions-Policy": (
                "camera=(), microphone=(), geolocation=(), "
                "payment=(), usb=(), magnetometer=(), "
                "accelerometer=(), gyroscope=()"
            ),
            
            # HTTP Strict Transport Security
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            
            # Защита от XSS (устаревший, но поддерживаемый)
            "X-XSS-Protection": "1; mode=block",
        }
    
    def update_header(self, header: str, value: str) -> None:
        """
        Обновление значения конкретного заголовка безопасности
        
        Args:
            header: Имя заголовка
            value: Новое значение
        """
        self.security_headers[header] = value
    
    def remove_header(self, header: str) -> None:
        """
        Удаление заголовка безопасности
        
        Args:
            header: Имя заголовка для удаления
        """
        if header in self.security_headers:
            del self.security_headers[header]


def setup_security_headers(app: FastAPI, custom_headers: Dict[str, str] = None) -> None:
    """
    Настройка middleware для защитных заголовков в FastAPI приложении
    
    Args:
        app: FastAPI приложение
        custom_headers: Пользовательские заголовки для добавления/переопределения
    """
    # Создаем middleware
    middleware = SecurityHeadersMiddleware(app)
    
    # Применяем пользовательские заголовки если они есть
    if custom_headers:
        for header, value in custom_headers.items():
            middleware.update_header(header, value)
    
    # Добавляем middleware в приложение
    app.add_middleware(SecurityHeadersMiddleware)


# Альтернативная реализация как декоратор для роутов
def security_headers_decorator(headers: Dict[str, str] = None):
    """
    Декоратор для добавления защитных заголовков к конкретным роутам
    
    Args:
        headers: Пользовательские заголовки (по умолчанию используются стандартные)
    
    Returns:
        Декорированную функцию
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            from fastapi.responses import JSONResponse
            
            # Выполняем оригинальную функцию
            response = await func(*args, **kwargs)
            
            # Добавляем заголовки к ответу
            security_headers = headers or SecurityHeadersMiddleware._get_default_headers(None)
            
            if isinstance(response, JSONResponse):
                for header, value in security_headers.items():
                    response.headers[header] = value
            
            return response
        
        return wrapper
    
    return decorator


# Пример использования в FastAPI
def add_security_middleware(app: FastAPI) -> None:
    """
    Добавляет middleware безопасности в FastAPI приложение
    
    Args:
        app: FastAPI приложение
    """
    # Настройка пользовательских заголовков (опционально)
    custom_headers = {
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline';"
        ),
        "X-Content-Type-Options": "nosniff",
    }
    
    setup_security_headers(app, custom_headers)