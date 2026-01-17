import time
import hmac
import hashlib
from typing import Final, Optional
from redis import Redis
from fastapi import FastAPI, Response, HTTPException, status
from pydantic import BaseModel, Field

# --- Конфигурация безопасности ---
MAX_LOGIN_ATTEMPTS: Final[int] = 5
LOCKOUT_DURATION_SECONDS: Final[int] = 900  # 15 минут
SESSION_EXPIRY_SECONDS: Final[int] = 3600    # 1 час

app = FastAPI()
# Инициализация Redis для хранения счетчиков попыток и сессий
redis_client = Redis(host='localhost', port=6379, db=0, decode_responses=True)

class LoginRequest(BaseModel):
    """Схема входящих данных для аутентификации."""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)

class AuthService:
    """Сервис аутентификации с защитой от Brute-force и безопасными сессиями."""

    def __init__(self, redis: Redis):
        self.redis = redis
        # Имитация БД: username -> argon2_hashed_password
        self._user_db = {
            "admin": "$argon2id$v=19$m=65536,t=3,p=4$..." 
        }

    def _get_attempts_key(self, username: str) -> str:
        return f"auth_attempts:{username}"

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Безопасная проверка пароля (в реальности использовать passlib.argon2)."""
        # Имитация константного времени сравнения для защиты от Timing Attack
        return hmac.compare_digest(
            hashlib.sha256(plain_password.encode()).hexdigest(),
            hashlib.sha256("stored_pass".encode()).hexdigest()
        )

    async def authenticate(self, credentials: LoginRequest, response: Response):
        username = credentials.username
        attempts_key = self._get_attempts_key(username)

        # 1. Проверка блокировки аккаунта
        attempts = self.redis.get(attempts_key)
        if attempts and int(attempts) >= MAX_LOGIN_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account temporarily locked. Try again later."
            )

        # 2. Имитация получения хеша из БД и проверка пароля
        user_hash = self._user_db.get(username)
        is_valid = user_hash and self._verify_password(credentials.password, user_hash)

        if not is_valid:
            # Увеличиваем счетчик неудачных попыток
            new_attempts = self.redis.incr(attempts_key)
            if new_attempts == 1:
                self.redis.expire(attempts_key, LOCKOUT_DURATION_SECONDS)
            
            # Обобщенное сообщение об ошибке для защиты от перебора имен пользователей
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials."
            )

        # 3. Успешный вход: сброс счетчика попыток
        self.redis.delete(attempts_key)

        # 4. Создание защищенной сессии
        session_id = secrets.token_urlsafe(32)
        self.redis.setex(f"session:{session_id}", SESSION_EXPIRY_SECONDS, username)

        # 5. Установка Cookie со строгими атрибутами безопасности
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,   # Защита от XSS: запрет доступа через JS (document.cookie)
            secure=True,     # Передача только по HTTPS
            samesite="strict", # Защита от CSRF: запрет отправки cookie при кросс-доменных запросах
            max_age=SESSION_EXPIRY_SECONDS,
            path="/"
        )
        return {"status": "authenticated"}

@app.post("/login")
async def login(credentials: LoginRequest, response: Response):
    service = AuthService(redis_client)
    return await service.authenticate(credentials, response)