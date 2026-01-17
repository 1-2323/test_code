from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware для внедрения строгих заголовков безопасности.
    Защищает от XSS, Clickjacking, Sniffing и принудительно переводит на HTTPS.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # 1. Content Security Policy (CSP)
        # Устанавливаем максимально строгую политику: запрещаем всё по умолчанию (default-src 'none')
        # Разрешаем только скрипты и стили с собственного домена ('self')
        csp_policy = (
            "default-src 'none'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; " # Запрещает встраивание сайта в <iframe> (защита от Clickjacking)
            "upgrade-insecure-requests;" # Автоматически переводит HTTP-ссылки в HTTPS
        )

        # 2. HTTP Strict Transport Security (HSTS)
        # Принуждает браузер использовать только HTTPS в течение 1 года (includeSubDomains включает поддомены)
        hsts_policy = "max-age=31536000; includeSubDomains; preload"

        # 3. Добавление заголовков в ответ
        headers = {
            "Content-Security-Policy": csp_policy,
            "Strict-Transport-Security": hsts_policy,
            "X-Frame-Options": "DENY",                 # Запрещает отображение страницы в фреймах
            "X-Content-Type-Options": "nosniff",       # Отключает MIME-sniffing (защита от подмены типов файлов)
            "X-XSS-Protection": "0",                   # Отключаем устаревший фильтр в пользу CSP
            "Referrer-Policy": "strict-origin-when-cross-origin", # Скрывает полный URL при переходе на другие сайты
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()" # Отключает доступ к API браузера
        }

        for key, value in headers.items():
            response.headers[key] = value

        return response

# --- Инициализация приложения ---

app = FastAPI()
app.add_middleware(SecurityHeadersMiddleware)

@app.get("/")
async def root():
    return {"message": "Security headers are active"}