from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware для защиты веб-приложения путем добавления заголовков безопасности.
    Помогает предотвратить XSS, Clickjacking и MIME-sniffing атаки.
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        
        # 1. Content Security Policy (CSP)
        # Ограничивает источники, из которых разрешена загрузка ресурсов.
        # Здесь: разрешено все только со своего домена.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "object-src 'none';"
        )
        
        # 2. HTTP Strict Transport Security (HSTS)
        # Принуждает браузер использовать только HTTPS в течение 1 года.
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        
        # 3. X-Content-Type-Options
        # Запрещает браузеру угадывать MIME-тип контента (защита от sniffing).
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # 4. X-Frame-Options
        # Защита от Clickjacking: запрещает отображать сайт во фреймах.
        response.headers["X-Frame-Options"] = "DENY"
        
        # 5. X-XSS-Protection
        # Включает встроенный в браузер фильтр межсайтового скриптинга.
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # 6. Referrer-Policy
        # Ограничивает передачу URL в заголовке Referer при переходах.
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response

# --- Инициализация приложения ---

app = FastAPI()

# Регистрация Middleware
app.add_middleware(SecurityHeadersMiddleware)

@app.get("/")
async def root():
    return {"message": "Сервер защищен заголовками безопасности"}

if __name__ == "__main__":
    import uvicorn
    # Запуск: uvicorn main:app --reload
    print("Middleware активен. Все заголовки будут добавлены ко всем ответам.")