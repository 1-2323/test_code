import hashlib
from fastapi import FastAPI, Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, Dict

class SessionSentinel:
    """
    Система мониторинга и валидации контекста сессии.
    Хранит слепки безопасности для активных сессий.
    """
    
    def __init__(self):
        # В продакшене использовать Redis с TTL
        # Структура: { session_id: {"ip": str, "fingerprint": str, "user_id": int} }
        self._active_sessions: Dict[str, Dict] = {}

    def _generate_fingerprint(self, request: Request) -> str:
        """
        Создает уникальный хеш браузера на основе заголовков.
        Используются данные, которые редко меняются в рамках одной сессии.
        """
        user_agent = request.headers.get("user-agent", "")
        accept_lang = request.headers.get("accept-language", "")
        # Можно добавить дополнительные заголовки для точности
        raw_fp = f"{user_agent}|{accept_lang}"
        return hashlib.sha256(raw_fp.encode()).hexdigest()

    def register_session(self, session_id: str, user_id: int, request: Request):
        """Фиксирует данные безопасности при входе в систему."""
        self._active_sessions[session_id] = {
            "user_id": user_id,
            "ip": request.client.host,
            "fingerprint": self._generate_fingerprint(request)
        }

    def validate_session(self, session_id: str, request: Request) -> bool:
        """Сверяет текущий контекст запроса с эталонным в сессии."""
        session_data = self._active_sessions.get(session_id)
        if not session_data:
            return False

        current_ip = request.client.host
        current_fp = self._generate_fingerprint(request)

        # Проверка на подмену IP или Fingerprint (Session Hijacking protection)
        if session_data["ip"] != current_ip or session_data["fingerprint"] != current_fp:
            # Немедленная инвалидация подозрительной сессии
            del self._active_sessions[session_id]
            return False

        return True

# Глобальный провайдер сессий
sentinel = SessionSentinel()

class SessionSecurityMiddleware(BaseHTTPMiddleware):
    """
    Middleware для автоматической проверки каждой активной сессии.
    """
    async def dispatch(self, request: Request, call_next):
        # Пропускаем проверку для эндпоинтов авторизации
        if request.url.path in ["/login", "/docs", "/openapi.json"]:
            return await call_next(request)

        session_id = request.cookies.get("session_id")
        
        if session_id:
            if not sentinel.validate_session(session_id, request):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Security context changed. Session terminated."
                )
        
        return await call_next(request)

# --- Инициализация FastAPI ---

app = FastAPI()
app.add_middleware(SessionSecurityMiddleware)

@app.post("/login")
async def login(request: Request):
    """Эндпоинт входа, где фиксируется слепок устройства."""
    session_id = "test-session-uuid-123" # В реальности генерируется случайно
    sentinel.register_session(session_id, user_id=1, request=request)
    
    from fastapi.responses import JSONResponse
    response = JSONResponse(content={"message": "Logged in"})
    response.set_cookie(key="session_id", value=session_id, httponly=True)
    return response

@app.get("/secure-data")
async def get_data():
    return {"data": "This is protected by device fingerprinting"}

if __name__ == "__main__":
    import uvicorn
    print("SessionSentinel активен. Проверка IP и Fingerprint включена.")
    # uvicorn.run(app, host="0.0.0.0", port=8000)