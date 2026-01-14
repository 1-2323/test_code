from fastapi import FastAPI, Request
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, List, Optional, Union
import re


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware для добавления HTTP-заголовков безопасности ко всем ответам.
    
    Реализует современные практики безопасности для веб-приложений.
    """
    
    def __init__(
        self,
        app,
        *,
        # Основные заголовки безопасности
        hsts_max_age: int = 31536000,  # 1 год в секундах
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = False,
        x_content_type_options: bool = True,
        x_frame_options: str = "DENY",
        x_xss_protection: str = "1; mode=block",
        referrer_policy: str = "strict-origin-when-cross-origin",
        permissions_policy: Dict[str, Union[List[str], str]] = None,
        # CSP конфигурация
        csp_enabled: bool = True,
        csp_report_only: bool = False,
        csp_directives: Dict[str, List[str]] = None,
        # Дополнительные настройки
        remove_server_header: bool = True,
        remove_powered_by_header: bool = True,
        force_https: bool = False,
        # Feature Policy / Permissions Policy
        feature_policy: Dict[str, List[str]] = None,
        # Expect-CT (устарело, но для совместимости)
        expect_ct_enabled: bool = False,
        expect_ct_max_age: int = 86400,
        expect_ct_enforce: bool = False,
        expect_ct_report_uri: Optional[str] = None,
    ):
        super().__init__(app)
        
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.hsts_preload = hsts_preload
        self.x_content_type_options = x_content_type_options
        self.x_frame_options = x_frame_options
        self.x_xss_protection = x_xss_protection
        self.referrer_policy = referrer_policy
        self.remove_server_header = remove_server_header
        self.remove_powered_by_header = remove_powered_by_header
        self.force_https = force_https
        self.csp_enabled = csp_enabled
        self.csp_report_only = csp_report_only
        self.expect_ct_enabled = expect_ct_enabled
        self.expect_ct_max_age = expect_ct_max_age
        self.expect_ct_enforce = expect_ct_enforce
        self.expect_ct_report_uri = expect_ct_report_uri
        
        # Настройка Permissions Policy
        if permissions_policy is None:
            self.permissions_policy = {
                "accelerometer": ["self"],
                "ambient-light-sensor": ["self"],
                "autoplay": ["self"],
                "battery": ["self"],
                "camera": ["self"],
                "display-capture": ["self"],
                "document-domain": ["self"],
                "encrypted-media": ["self"],
                "execution-while-not-rendered": ["self"],
                "execution-while-out-of-viewport": ["self"],
                "fullscreen": ["self"],
                "gamepad": ["self"],
                "geolocation": ["self"],
                "gyroscope": ["self"],
                "layout-animations": ["self"],
                "legacy-image-formats": ["self"],
                "magnetometer": ["self"],
                "microphone": ["self"],
                "midi": ["self"],
                "navigation-override": ["self"],
                "payment": ["self"],
                "picture-in-picture": ["self"],
                "publickey-credentials-get": ["self"],
                "screen-wake-lock": ["self"],
                "sync-xhr": ["self"],
                "usb": ["self"],
                "web-share": ["self"],
                "xr-spatial-tracking": ["self"],
            }
        else:
            self.permissions_policy = permissions_policy
        
        # Настройка Feature Policy (устарело, но для совместимости)
        self.feature_policy = feature_policy or {}
        
        # Настройка Content Security Policy (CSP)
        if csp_directives is None:
            self.csp_directives = {
                "default-src": ["'self'"],
                "script-src": [
                    "'self'",
                    "'unsafe-inline'",
                    "'unsafe-eval'",
                    "https://cdn.jsdelivr.net",
                    "https://unpkg.com",
                ],
                "style-src": [
                    "'self'",
                    "'unsafe-inline'",
                    "https://cdn.jsdelivr.net",
                    "https://fonts.googleapis.com",
                ],
                "img-src": [
                    "'self'",
                    "data:",
                    "https:",
                    "http:",
                ],
                "font-src": [
                    "'self'",
                    "https://fonts.gstatic.com",
                    "https://cdn.jsdelivr.net",
                ],
                "connect-src": [
                    "'self'",
                    "https://api.example.com",
                    "wss://ws.example.com",
                ],
                "frame-src": ["'self'"],
                "object-src": ["'none'"],
                "media-src": ["'self'"],
                "manifest-src": ["'self'"],
                "worker-src": ["'self'"],
                "child-src": ["'self'"],
                "form-action": ["'self'"],
                "frame-ancestors": ["'none'"],
                "base-uri": ["'self'"],
                "report-uri": ["/api/security/csp-report"],
                "report-to": ["csp-endpoint"],
            }
        else:
            self.csp_directives = csp_directives
    
    def build_hsts_header(self) -> str:
        """Создание HSTS заголовка"""
        hsts_parts = [f"max-age={self.hsts_max_age}"]
        
        if self.hsts_include_subdomains:
            hsts_parts.append("includeSubDomains")
        
        if self.hsts_preload:
            hsts_parts.append("preload")
        
        return "; ".join(hsts_parts)
    
    def build_csp_header(self) -> str:
        """Создание CSP заголовка"""
        if not self.csp_enabled:
            return ""
        
        directives = []
        
        for directive, sources in self.csp_directives.items():
            if sources:
                # Фильтруем пустые значения и объединяем источники
                filtered_sources = [src for src in sources if src]
                if filtered_sources:
                    directives.append(f"{directive} {' '.join(filtered_sources)}")
        
        return "; ".join(directives)
    
    def build_permissions_policy_header(self) -> str:
        """Создание Permissions Policy заголовка"""
        policies = []
        
        for feature, origins in self.permissions_policy.items():
            if isinstance(origins, list):
                origins_str = ", ".join([f'"{origin}"' for origin in origins])
            elif isinstance(origins, str):
                origins_str = f'"{origins}"'
            else:
                continue
            
            policies.append(f"{feature}=({origins_str})")
        
        return ", ".join(policies)
    
    def build_feature_policy_header(self) -> str:
        """Создание Feature Policy заголовка (устарело)"""
        if not self.feature_policy:
            return ""
        
        policies = []
        
        for feature, origins in self.feature_policy.items():
            if origins:
                origins_str = " ".join([f"'{origin}'" for origin in origins])
                policies.append(f"{feature} {origins_str}")
        
        return "; ".join(policies)
    
    def build_expect_ct_header(self) -> Optional[str]:
        """Создание Expect-CT заголовка"""
        if not self.expect_ct_enabled:
            return None
        
        expect_ct_parts = [f"max-age={self.expect_ct_max_age}"]
        
        if self.expect_ct_enforce:
            expect_ct_parts.append("enforce")
        
        if self.expect_ct_report_uri:
            expect_ct_parts.append(f'report-uri="{self.expect_ct_report_uri}"')
        
        return ", ".join(expect_ct_parts)
    
    def is_excluded_path(self, path: str) -> bool:
        """
        Проверка, нужно ли исключить путь из добавления заголовков безопасности.
        
        Некоторые пути (например, статические файлы, health checks) могут не требовать
        всех заголовков безопасности.
        """
        excluded_patterns = [
            r'^/health$',
            r'^/healthz$',
            r'^/ready$',
            r'^/metrics$',
            r'^/static/',
            r'^/media/',
            r'^/favicon\.ico$',
            r'^/robots\.txt$',
        ]
        
        for pattern in excluded_patterns:
            if re.match(pattern, path):
                return True
        
        return False
    
    async def dispatch(self, request: Request, call_next):
        """Обработка каждого запроса и добавление заголовков безопасности"""
        
        # Получаем ответ от приложения
        response = await call_next(request)
        
        # Проверяем, нужно ли исключить путь
        if self.is_excluded_path(request.url.path):
            return response
        
        # Удаляем нежелательные заголовки
        if self.remove_server_header and "server" in response.headers:
            del response.headers["server"]
        
        if self.remove_powered_by_header and "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]
        
        # Добавляем заголовки безопасности
        
        # 1. Strict-Transport-Security (HSTS)
        if self.force_https:
            hsts_header = self.build_hsts_header()
            if hsts_header:
                response.headers["Strict-Transport-Security"] = hsts_header
        
        # 2. X-Content-Type-Options
        if self.x_content_type_options:
            response.headers["X-Content-Type-Options"] = "nosniff"
        
        # 3. X-Frame-Options
        if self.x_frame_options:
            response.headers["X-Frame-Options"] = self.x_frame_options
        
        # 4. X-XSS-Protection
        if self.x_xss_protection:
            response.headers["X-XSS-Protection"] = self.x_xss_protection
        
        # 5. Referrer-Policy
        if self.referrer_policy:
            response.headers["Referrer-Policy"] = self.referrer_policy
        
        # 6. Permissions-Policy
        permissions_policy_header = self.build_permissions_policy_header()
        if permissions_policy_header:
            response.headers["Permissions-Policy"] = permissions_policy_header
        
        # 7. Feature-Policy (устарело, но для совместимости)
        feature_policy_header = self.build_feature_policy_header()
        if feature_policy_header:
            response.headers["Feature-Policy"] = feature_policy_header
        
        # 8. Content-Security-Policy
        csp_header = self.build_csp_header()
        if csp_header:
            if self.csp_report_only:
                response.headers["Content-Security-Policy-Report-Only"] = csp_header
            else:
                response.headers["Content-Security-Policy"] = csp_header
        
        # 9. Expect-CT (Certificate Transparency)
        expect_ct_header = self.build_expect_ct_header()
        if expect_ct_header:
            response.headers["Expect-CT"] = expect_ct_header
        
        # 10. Cache-Control для чувствительных ответов
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            if "cache-control" not in response.headers:
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        
        # 11. Дополнительные современные заголовки
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        
        # 12. Предотвращение MIME-сниффинга
        response.headers["X-Download-Options"] = "noopen"
        
        # 13. Заголовки для CORS (если не настроены отдельно)
        if "access-control-allow-origin" not in response.headers:
            # Базовые настройки для API
            if request.url.path.startswith("/api/"):
                response.headers["Access-Control-Allow-Credentials"] = "true"
        
        return response


class SecurityHeadersConfig:
    """Конфигурация для заголовков безопасности"""
    
    def __init__(
        self,
        *,
        # Режимы безопасности
        security_level: str = "strict",  # "minimal", "standard", "strict"
        environment: str = "production",  # "development", "staging", "production"
        # Домены и источники
        allowed_domains: List[str] = None,
        api_domains: List[str] = None,
        cdn_domains: List[str] = None,
        # Дополнительные настройки
        enable_csp_nonces: bool = False,
        enable_reporting: bool = True,
        report_endpoint: str = "/api/security/report",
    ):
        self.security_level = security_level
        self.environment = environment
        self.allowed_domains = allowed_domains or []
        self.api_domains = api_domains or []
        self.cdn_domains = cdn_domains or []
        self.enable_csp_nonces = enable_csp_nonces
        self.enable_reporting = enable_reporting
        self.report_endpoint = report_endpoint
        
        # Настройки в зависимости от среды
        self._configure_by_environment()
    
    def _configure_by_environment(self):
        """Настройка параметров в зависимости от среды выполнения"""
        
        if self.environment == "development":
            # Более мягкие настройки для разработки
            self.csp_report_only = True
            self.force_https = False
            self.hsts_max_age = 3600  # 1 час
            
            # Разрешаем больше источников для разработки
            if not self.allowed_domains:
                self.allowed_domains = ["'self'", "localhost:*", "127.0.0.1:*"]
        
        elif self.environment == "production":
            # Строгие настройки для продакшена
            self.csp_report_only = False
            self.force_https = True
            self.hsts_max_age = 31536000  # 1 год
            self.hsts_preload = True
            
            if not self.allowed_domains:
                self.allowed_domains = ["'self'"]
        
        elif self.environment == "staging":
            # Промежуточные настройки для staging
            self.csp_report_only = True
            self.force_https = True
            self.hsts_max_age = 86400  # 1 день
    
    def get_middleware_kwargs(self) -> dict:
        """Получение аргументов для создания middleware"""
        
        # Базовые CSP директивы
        csp_directives = {
            "default-src": ["'self'"] + self.allowed_domains,
            "script-src": ["'self'"] + self.cdn_domains,
            "style-src": ["'self'", "'unsafe-inline'"] + self.cdn_domains,
            "img-src": ["'self'", "data:", "https:"] + self.cdn_domains,
            "connect-src": ["'self'"] + self.api_domains,
            "font-src": ["'self'"] + self.cdn_domains,
            "object-src": ["'none'"],
            "media-src": ["'self'"],
            "frame-src": ["'none'"],
            "child-src": ["'self'"],
            "form-action": ["'self'"],
            "frame-ancestors": ["'none'"],
            "base-uri": ["'self'"],
        }
        
        # Добавляем nonce если включено
        if self.enable_csp_nonces:
            csp_directives["script-src"].append("'nonce-{nonce}'")
            csp_directives["style-src"].append("'nonce-{nonce}'")
        
        # Добавляем reporting если включено
        if self.enable_reporting:
            csp_directives["report-uri"] = [self.report_endpoint]
            csp_directives["report-to"] = ["security-endpoint"]
        
        # Настройка в зависимости от уровня безопасности
        if self.security_level == "strict":
            x_frame_options = "DENY"
            referrer_policy = "no-referrer"
            csp_directives["upgrade-insecure-requests"] = [""]
            
        elif self.security_level == "standard":
            x_frame_options = "SAMEORIGIN"
            referrer_policy = "strict-origin-when-cross-origin"
            
        else:  # minimal
            x_frame_options = "SAMEORIGIN"
            referrer_policy = "no-referrer-when-downgrade"
            csp_directives["script-src"].append("'unsafe-inline'")
            csp_directives["script-src"].append("'unsafe-eval'")
        
        return {
            "force_https": self.force_https,
            "hsts_max_age": self.hsts_max_age,
            "hsts_preload": self.hsts_preload,
            "x_frame_options": x_frame_options,
            "referrer_policy": referrer_policy,
            "csp_enabled": True,
            "csp_report_only": self.csp_report_only,
            "csp_directives": csp_directives,
            "remove_server_header": True,
            "remove_powered_by_header": True,
        }


def setup_security_headers(
    app: FastAPI,
    config: Optional[SecurityHeadersConfig] = None
):
    """
    Настройка заголовков безопасности для FastAPI приложения.
    
    Args:
        app: FastAPI приложение
        config: Конфигурация безопасности (опционально)
    """
    
    if config is None:
        config = SecurityHeadersConfig()
    
    # Получаем настройки для middleware
    middleware_kwargs = config.get_middleware_kwargs()
    
    # Добавляем HTTPS редирект если включено
    if middleware_kwargs.get("force_https", False):
        app.add_middleware(HTTPSRedirectMiddleware)
    
    # Добавляем middleware заголовков безопасности
    app.add_middleware(SecurityHeadersMiddleware, **middleware_kwargs)
    
    # Добавляем endpoint для отчетов о нарушениях безопасности
    if config.enable_reporting:
        
        @app.post(config.report_endpoint)
        async def security_report_endpoint(report: dict):
            """
            Endpoint для получения отчетов о нарушениях безопасности.
            Используется CSP, Expect-CT и другие механизмы отчетов.
            """
            # Здесь можно сохранить отчет в базу данных, отправить уведомление и т.д.
            # В продакшене следует добавить аутентификацию и валидацию
            
            # Логируем отчет
            import logging
            security_logger = logging.getLogger("security")
            security_logger.warning(f"Security violation report: {report}")
            
            return {"status": "received"}


# Пример использования с FastAPI
def create_secure_app() -> FastAPI:
    """Создание FastAPI приложения с настроенными заголовками безопасности"""
    
    from fastapi import FastAPI
    
    app = FastAPI(
        title="Secure API",
        description="API с настроенными заголовками безопасности",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json"
    )
    
    # Конфигурация для продакшена
    config = SecurityHeadersConfig(
        security_level="strict",
        environment="production",
        allowed_domains=["https://example.com"],
        api_domains=["https://api.example.com"],
        cdn_domains=["https://cdn.example.com"],
        enable_reporting=True,
        report_endpoint="/api/security/csp-report"
    )
    
    # Настройка заголовков безопасности
    setup_security_headers(app, config)
    
    # Пример маршрутов
    @app.get("/")
    async def root():
        return {"message": "Secure API"}
    
    @app.get("/api/health")
    async def health_check():
        """Health check endpoint (без строгих заголовков безопасности)"""
        return {"status": "healthy"}
    
    @app.get("/api/data")
    async def get_data():
        """Endpoint с данными (полная защита)"""
        return {"data": [1, 2, 3, 4, 5]}
    
    return app


# Декоратор для добавления nonce в ответы
def add_csp_nonce(request: Request, response: Response):
    """Добавление nonce для CSP в ответ"""
    
    import secrets
    
    # Генерируем уникальный nonce для каждого запроса
    nonce = secrets.token_urlsafe(32)
    
    # Сохраняем nonce в состоянии запроса
    request.state.csp_nonce = nonce
    
    # Если в CSP есть {nonce}, заменяем его
    if "Content-Security-Policy" in response.headers:
        csp_header = response.headers["Content-Security-Policy"]
        response.headers["Content-Security-Policy"] = csp_header.replace(
            "'nonce-{nonce}'", f"'nonce-{nonce}'"
        )
    
    # Также добавляем nonce как заголовок для использования в шаблонах
    response.headers["X-CSP-Nonce"] = nonce
    
    return nonce


# Middleware для добавления nonce
class CSPNonceMiddleware(BaseHTTPMiddleware):
    """Middleware для добавления CSP nonce в каждый запрос"""
    
    async def dispatch(self, request: Request, call_next):
        # Добавляем nonce в состояние запроса
        import secrets
        request.state.csp_nonce = secrets.token_urlsafe(32)
        
        # Получаем ответ
        response = await call_next(request)
        
        # Обновляем CSP header с nonce
        if "Content-Security-Policy" in response.headers:
            csp_header = response.headers["Content-Security-Policy"]
            updated_csp = csp_header.replace(
                "'nonce-{nonce}'", f"'nonce-{request.state.csp_nonce}'"
            )
            response.headers["Content-Security-Policy"] = updated_csp
        
        return response


# Утилиты для работы с заголовками безопасности
class SecurityHeadersUtils:
    """Утилиты для работы с заголовками безопасности"""
    
    @staticmethod
    def get_recommended_headers(level: str = "standard") -> Dict[str, str]:
        """Получение рекомендуемых заголовков безопасности для разных уровней"""
        
        recommendations = {
            "minimal": {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
            },
            "standard": {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            },
            "strict": {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Cross-Origin-Embedder-Policy": "require-corp",
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Resource-Policy": "same-origin",
            }
        }
        
        return recommendations.get(level, recommendations["standard"])
    
    @staticmethod
    def generate_csp_nonce() -> str:
        """Генерация nonce для CSP"""
        import secrets
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def validate_csp_directives(directives: Dict[str, List[str]]) -> List[str]:
        """Валидация CSP директив"""
        
        errors = []
        required_directives = ["default-src"]
        
        for required in required_directives:
            if required not in directives:
                errors.append(f"Missing required CSP directive: {required}")
        
        # Проверка значений
        for directive, sources in directives.items():
            for source in sources:
                if not SecurityHeadersUtils.is_valid_csp_source(source):
                    errors.append(f"Invalid CSP source in {directive}: {source}")
        
        return errors
    
    @staticmethod
    def is_valid_csp_source(source: str) -> bool:
        """Проверка валидности CSP источника"""
        
        # Разрешенные ключевые слова
        keywords = [
            "'self'", "'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'",
            "'unsafe-allow-redirects'", "'none'", "'strict-dynamic'",
            "'report-sample'", "'wasm-unsafe-eval'"
        ]
        
        if source in keywords:
            return True
        
        # Проверка схем
        if source in ["http:", "https:", "data:", "mediastream:", "blob:", "filesystem:"]:
            return True
        
        # Проверка доменов
        import re
        domain_pattern = re.compile(
            r'^https?://[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
            r'(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*(:[0-9]{1,5})?$'
        )
        
        if domain_pattern.match(source):
            return True
        
        # Nonce или hash
        if source.startswith("'nonce-") and source.endswith("'"):
            return True
        
        if source.startswith("'sha256-") or source.startswith("'sha384-") or source.startswith("'sha512-"):
            return True
        
        return False


# Пример использования в существующем приложении
def setup_existing_app_security(app: FastAPI):
    """Быстрая настройка безопасности для существующего приложения"""
    
    # Быстрая конфигурация
    config = SecurityHeadersConfig(
        security_level="standard",
        environment="production"
    )
    
    # Настройка middleware
    setup_security_headers(app, config)
    
    # Логирование инициализации
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Security headers middleware initialized")


if __name__ == "__main__":
    # Пример запуска приложения с защитой
    import uvicorn
    
    app = create_secure_app()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ssl_keyfile="path/to/key.pem",  # Для HTTPS
        ssl_certfile="path/to/cert.pem"  # Для HTTPS
    )