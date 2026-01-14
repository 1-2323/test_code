import re
from typing import Callable
from datetime import datetime, timedelta

class SecurityHeadersMiddleware:
    """
    Middleware для добавления HTTP-заголовков безопасности ко всем ответам.
    """
    
    def __init__(self, get_response: Callable):
        self.get_response = get_response
        
        # Конфигурация CSP (можно настраивать)
        self.csp_directives = {
            'default-src': ["'self'"],
            'script-src': ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
            'style-src': ["'self'", "'unsafe-inline'"],
            'img-src': ["'self'", "data:", "https:"],
            'font-src': ["'self'", "https:", "data:"],
            'connect-src': ["'self'"],
            'media-src': ["'self'"],
            'object-src': ["'none'"],
            'frame-src': ["'none'"],
            'frame-ancestors': ["'none'"],
            'base-uri': ["'self'"],
            'form-action': ["'self'"],
            'upgrade-insecure-requests': [],
            'block-all-mixed-content': []
        }
        
        # HSTS настройки (максимальное время - 1 год)
        self.hsts_max_age = 31536000  # 365 дней в секундах
        self.hsts_include_subdomains = True
        self.hsts_preload = False
        
    def __call__(self, request):
        # Получаем ответ от следующего middleware или view
        response = self.get_response(request)
        
        # Добавляем все заголовки безопасности
        self._add_security_headers(response)
        
        return response
    
    def _add_security_headers(self, response):
        """
        Добавляет все заголовки безопасности к ответу.
        """
        # 1. Strict-Transport-Security (HSTS)
        self._add_hsts_header(response)
        
        # 2. Content-Security-Policy
        self._add_csp_header(response)
        
        # 3. X-Content-Type-Options
        response['X-Content-Type-Options'] = 'nosniff'
        
        # 4. Дополнительные рекомендуемые заголовки
        self._add_additional_headers(response)
        
        return response
    
    def _add_hsts_header(self, response):
        """
        Добавляет заголовок Strict-Transport-Security.
        """
        hsts_value = f"max-age={self.hsts_max_age}"
        
        if self.hsts_include_subdomains:
            hsts_value += "; includeSubDomains"
        
        if self.hsts_preload:
            hsts_value += "; preload"
            
        response['Strict-Transport-Security'] = hsts_value
    
    def _add_csp_header(self, response):
        """
        Формирует и добавляет заголовок Content-Security-Policy.
        """
        csp_parts = []
        
        for directive, sources in self.csp_directives.items():
            if sources:
                sources_str = " ".join(sources)
                csp_parts.append(f"{directive} {sources_str}")
            else:
                csp_parts.append(directive)
        
        csp_value = "; ".join(csp_parts)
        
        # Добавляем оба заголовка для обратной совместимости
        response['Content-Security-Policy'] = csp_value
        response['X-Content-Security-Policy'] = csp_value  # Для IE
    
    def _add_additional_headers(self, response):
        """
        Добавляет дополнительные рекомендуемые заголовки безопасности.
        """
        # Заголовки для предотвращения кликджекинга
        response['X-Frame-Options'] = 'DENY'
        
        # Контроль реферера
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Политика разрешений
        response['Permissions-Policy'] = (
            'geolocation=(), microphone=(), camera=(), payment=()'
        )
        
        # Отключение сниффинга MIME типов в старых IE
        response['X-Download-Options'] = 'noopen'
        
        # Предотвращение XSS в старых браузерах
        if 'text/html' in response.get('Content-Type', ''):
            response['X-XSS-Protection'] = '1; mode=block'
    
    def update_csp_directive(self, directive: str, sources: list):
        """
        Позволяет обновлять директивы CSP динамически.
        
        Args:
            directive: Директива CSP (например, 'script-src')
            sources: Список источников для директивы
        """
        if directive in self.csp_directives:
            self.csp_directives[directive] = sources
    
    def add_csp_directive(self, directive: str, sources: list):
        """
        Добавляет новую директиву CSP.
        
        Args:
            directive: Новая директива CSP
            sources: Список источников для директивы
        """
        self.csp_directives[directive] = sources
    
    @staticmethod
    def sanitize_csp_source(source: str) -> str:
        """
        Санитизирует источник CSP для безопасности.
        
        Args:
            source: Исходный источник
            
        Returns:
            Санитизированный источник
        """
        # Удаляем опасные символы
        sanitized = re.sub(r'[<>"\'\\]', '', source)
        
        # Проверяем, не является ли source уже заключенным в кавычки
        if not (sanitized.startswith("'") and sanitized.endswith("'")):
            # Если это не ключевое слово и не data:/blob:, оставляем как есть
            if not sanitized.startswith(('data:', 'blob:', 'https:', 'http:', 'ws:', 'wss:')):
                # Это может быть ключевое слово типа 'self', 'none' и т.д.
                if sanitized in ['self', 'none', 'unsafe-inline', 'unsafe-eval', 'strict-dynamic']:
                    sanitized = f"'{sanitized}'"
        
        return sanitized


# Пример использования с Django (дополнительный пример интеграции)
def django_middleware_example(get_response):
    """
    Пример использования middleware в Django.
    """
    security_middleware = SecurityHeadersMiddleware(get_response)
    
    def middleware(request):
        return security_middleware(request)
    
    return middleware


# Пример использования с Flask (дополнительный пример интеграции)
class FlaskSecurityHeaders:
    """
    Расширение для Flask для добавления заголовков безопасности.
    """
    
    def __init__(self, app=None):
        self.app = app
        self.security_middleware = None
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """
        Инициализирует расширение с приложением Flask.
        """
        self.security_middleware = SecurityHeadersMiddleware(lambda req: None)
        
        @app.after_request
        def add_security_headers(response):
            self.security_middleware._add_security_headers(response)
            return response
        
        # Делаем методы конфигурации доступными через расширение
        app.update_csp_directive = self.update_csp_directive
        app.add_csp_directive = self.add_csp_directive
    
    def update_csp_directive(self, directive: str, sources: list):
        """
        Прокси метод для обновления CSP.
        """
        if self.security_middleware:
            self.security_middleware.update_csp_directive(directive, sources)
    
    def add_csp_directive(self, directive: str, sources: list):
        """
        Прокси метод для добавления CSP.
        """
        if self.security_middleware:
            self.security_middleware.add_csp_directive(directive, sources)