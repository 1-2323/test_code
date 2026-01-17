import secrets
from typing import Optional, Final
from fastapi import FastAPI, Request, Response, HTTPException, status
from redis.asyncio import Redis

# --- Константы безопасности ---
SESSION_TTL: Final[int] = 3600  # 1 час
RECOVERY_TOKEN_TTL: Final[int] = 600  # 10 минут
COOKIE_NAME: Final[str] = "session_id"

app = FastAPI()
# Рекомендуется использовать защищенное соединение с Redis (rediss://)
redis_client = Redis(host='localhost', port=6379, db=0, decode_responses=True)

class SessionProvider:
    """
    Менеджер сессий, обеспечивающий жизненный цикл сессионных кук 
    и одноразовых токенов восстановления.
    """

    def __init__(self, redis: Redis):
        self.redis = redis

    def _generate_token(self) -> str:
        """Создает криптографически стойкий токен."""
        return secrets.token_urlsafe(48)

    async def create_session(self, response: Response, user_id: str, domain: Optional[str] = None):
        """
        Инициализирует сессию в Redis и устанавливает защищенную куку.
        """
        session_id = self._generate_token()
        
        # Сохранение сессии в Redis с привязкой к ID пользователя
        await self.redis.setex(
            name=f"session:{session_id}",
            time=SESSION_TTL,
            value=user_id
        )

        # Установка куки со строгими атрибутами безопасности
        response.set_cookie(
            key=COOKIE_NAME,
            value=session_id,
            max_age=SESSION_TTL,
            expires=SESSION_TTL,
            domain=domain,
            path="/",
            httponly=True,   # Защита от кражи через JS (XSS)
            secure=True,     # Только через HTTPS
            samesite="strict" # Защита от CSRF
        )
        return session_id

    async def invalidate_session(self, request: Request, response: Response):
        """
        Удаляет сессию из хранилища и очищает куку на стороне клиента.
        """
        session_id = request.cookies.get(COOKIE_NAME)
        if session_id:
            # Гарантированное удаление из Redis
            await self.redis.delete(f"session:{session_id}")
        
        # Очистка куки (установка срока действия в прошлом)
        response.delete_cookie(
            key=COOKIE_NAME,
            path="/",
            httponly=True,
            secure=True,
            samesite="strict"
        )

    async def create_one_time_recovery_token(self, user_id: str) -> str:
        """
        Создает временный токен для процедуры смены пароля.
        """
        token = self._generate_token()
        await self.redis.setex(
            name=f"recovery:{token}",
            time=RECOVERY_TOKEN_TTL,
            value=user_id
        )
        return token

    async def finalize_password_reset(self, token: str, new_password_hash: str):
        """
        Выполняет смену пароля и гарантированно удаляет токен (One-time use).
        """
        user_id = await self.redis.get(f"recovery:{token}")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired recovery token."
            )

        try:
            # 1. Логика обновления пароля в основной БД (SQL/NoSQL)
            # await db.users.update(user_id, hashed_password=new_password_hash)
            
            # 2. Инвалидация всех активных сессий пользователя при смене пароля (опционально)
            # await self._revoke_all_user_sessions(user_id)
            
            pass
        finally:
            # ГАРАНТИРОВАННОЕ удаление токена сразу после использования
            await self.redis.delete(f"recovery:{token}")



# --- Примеры эндпоинтов ---

@app.post("/auth/login")
async def login(response: Response):
    provider = SessionProvider(redis_client)
    # user_id получается после проверки учетных данных
    await provider.create_session(response, user_id="user_123")
    return {"message": "Logged in successfully"}

@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    provider = SessionProvider(redis_client)
    await provider.invalidate_session(request, response)
    return {"message": "Logged out"}

@app.post("/auth/reset-password-confirm")
async def reset_password(token: str, new_password: str):
    provider = SessionProvider(redis_client)
    # Пароль должен быть предварительно захеширован (например, Argon2)
    await provider.finalize_password_reset(token, "hashed_password_here")
    return {"message": "Password updated and token invalidated"}