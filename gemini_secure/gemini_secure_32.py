import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Final, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from passlib.context import CryptContext

# --- Настройки безопасности ---
TOKEN_BYTES: Final[int] = 32
TOKEN_TTL_MINUTES: Final[int] = 15
# Argon2 — современный и устойчивый к перебору алгоритм хеширования
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

app = FastAPI()
# Подключение к Redis для хранения хешированных токенов
redis_client = Redis(host='localhost', port=6379, db=0, decode_responses=True)

class PasswordResetConfirm(BaseModel):
    """Схема данных для подтверждения сброса пароля."""
    token: str = Field(..., description="Открытый токен из письма")
    new_password: str = Field(..., min_length=12, max_length=128)

class PasswordResetService:
    """Сервис для управления жизненным циклом токенов сброса пароля."""

    def __init__(self, redis: Redis):
        self.redis = redis

    def _hash_token(self, token: str) -> str:
        """Создает криптографический хеш токена для безопасного хранения."""
        return hashlib.sha256(token.encode()).hexdigest()

    async def create_reset_token(self, user_id: str) -> str:
        """Создает токен, сохраняет его хеш в Redis и возвращает оригинал."""
        raw_token = secrets.token_urlsafe(TOKEN_BYTES)
        token_hash = self._hash_token(raw_token)
        
        # Ключ включает хеш токена, значение — ID пользователя
        await self.redis.setex(
            name=f"reset_token:{token_hash}",
            time=timedelta(minutes=TOKEN_TTL_MINUTES),
            value=user_id
        )
        return raw_token

    async def confirm_reset(self, raw_token: str, new_password_plain: str):
        """Проверяет токен, обновляет пароль и немедленно удаляет токен."""
        token_hash = self._hash_token(raw_token)
        token_key = f"reset_token:{token_hash}"

        # 1. Атомарное получение ID пользователя по хешу токена
        user_id = await self.redis.get(token_key)
        
        if not user_id:
            # Ошибка возвращается без уточнения причины (истек или не существует) 
            # для защиты от перебора
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ссылка для сброса пароля недействительна или ее срок действия истек."
            )

        try:
            # 2. Хеширование нового пароля
            hashed_password = pwd_context.hash(new_password_plain)

            # 3. Атомарное обновление в основной базе данных
            # Здесь должен быть вызов к вашей БД (PostgreSQL/MongoDB)
            # await db.users.update_one({"id": user_id}, {"password": hashed_password})
            
            # Имитация успешного сохранения
            update_success = True 
            if not update_success:
                raise Exception("Database update failed")

        finally:
            # 4. Немедленная инвалидация токена (удаление из Redis)
            # Выполняется в блоке finally, чтобы токен стал недействительным 
            # в любом случае после попытки использования
            await self.redis.delete(token_key)

        return {"status": "success", "message": "Пароль успешно обновлен."}

# --- Эндпоинты ---

@app.post("/auth/password-reset-confirm", status_code=status.HTTP_200_OK)
async def confirm_password_reset(data: PasswordResetConfirm):
    """
    Эндпоинт подтверждения смены пароля.
    Принимает открытый токен, проверяет его хеш в хранилище и обновляет пароль.
    """
    service = PasswordResetService(redis_client)
    return await service.confirm_reset(data.token, data.new_password)