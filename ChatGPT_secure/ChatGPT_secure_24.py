from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Response


# =========================
# SECURITY HEADERS MIDDLEWARE
# =========================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware для добавления защитных HTTP-заголовков
    ко всем ответам сервера.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Content Security Policy — максимально строгая
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self'; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'self'"
        )

        # HTTP Strict Transport Security
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )

        # Запрет MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Запрет встраивания в iframe
        response.headers["X-Frame-Options"] = "DENY"

        # Минимизация утечки реферера
        response.headers["Referrer-Policy"] = "no-referrer"

        # Ограничение API браузера
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )

        return response


# =========================
# FASTAPI APPLICATION
# =========================

app = FastAPI(
    title="Secure API",
    version="1.0.0",
)

app.add_middleware(SecurityHeadersMiddleware)


# =========================
# SAMPLE ENDPOINT
# =========================

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
