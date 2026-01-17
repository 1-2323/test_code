from typing import Dict, Callable, Optional

# =========================
# Общая конфигурация
# =========================

class SecurityHeadersConfig:
    """
    Конфигурация защитных HTTP-заголовков.
    """

    def __init__(
        self,
        content_security_policy: str = (
            "default-src 'self'; "
            "img-src 'self' https: data:; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'"
        ),
        strict_transport_security: str = (
            "max-age=63072000; includeSubDomains; preload"
        ),
        x_content_type_options: str = "nosniff",
        x_frame_options: str = "DENY",
    ) -> None:
        self.headers: Dict[str, str] = {
            "Content-Security-Policy": content_security_policy,
            "Strict-Transport-Security": strict_transport_security,
            "X-Content-Type-Options": x_content_type_options,
            "X-Frame-Options": x_frame_options,
        }


# =========================
# FastAPI Middleware
# =========================

try:
    from fastapi import Request, Response, FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware

    class FastApiSecurityHeadersMiddleware(BaseHTTPMiddleware):
        """
        Middleware защитных заголовков для FastAPI.
        """

        def __init__(
            self,
            app: FastAPI,
            config: SecurityHeadersConfig,
        ) -> None:
            super().__init__(app)
            self._headers = config.headers

        async def dispatch(
            self,
            request: Request,
            call_next: Callable,
        ) -> Response:
            response: Response = await call_next(request)

            for header, value in self._headers.items():
                response.headers.setdefault(header, value)

            return response

except ImportError:
    FastApiSecurityHeadersMiddleware = None  # type: ignore


# =========================
# Flask Middleware
# =========================

try:
    from flask import Flask, Response

    class FlaskSecurityHeadersMiddleware:
        """
        Middleware защитных заголовков для Flask.
        """

        def __init__(
            self,
            app: Flask,
            config: SecurityHeadersConfig,
        ) -> None:
            self._headers = config.headers
            self._register(app)

        def _register(self, app: Flask) -> None:
            @app.after_request
            def apply_headers(response: Response) -> Response:
                for header, value in self._headers.items():
                    response.headers.setdefault(header, value)
                return response

except ImportError:
    FlaskSecurityHeadersMiddleware = None  # type: ignore


# =========================
# Универсальный helper
# =========================

def apply_security_headers(
    app: object,
    config: Optional[SecurityHeadersConfig] = None,
) -> None:
    """
    Автоматически подключает middleware
    в зависимости от типа приложения.
    """
    config = config or SecurityHeadersConfig()

    if FastApiSecurityHeadersMiddleware and hasattr(app, "add_middleware"):
        app.add_middleware(
            FastApiSecurityHeadersMiddleware,
            config=config,
        )
        return

    if FlaskSecurityHeadersMiddleware and hasattr(app, "after_request"):
        FlaskSecurityHeadersMiddleware(app, config)
        return

    raise RuntimeError("Unsupported application type")
