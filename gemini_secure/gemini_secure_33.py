import hmac
import secrets
import jwt
from datetime import datetime, timedelta
from typing import Final, Dict, Any
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

# --- Конфигурация безопасности ---
OTP_TTL: Final[int] = 300  # 5 минут
MAX_OTP_ATTEMPTS: Final[int] = 3
JWT_SECRET: Final[str] = "your-very-secure-secret-key"  # В продакшене из ENV
JWT_ALGORITHM: Final[str] = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: Final[int] = 15

app = FastAPI()
redis_client = Redis(host='localhost', port=6379, db=0, decode_responses=True)

class VerifyOTPRequest(BaseModel):
    """Схема запроса на верификацию OTP."""
    user_id: str = Field(..., min_length=1)
    otp_code: str = Field(..., min_length=6, max_length=6)

class TwoFactorService:
    """Сервис верификации 2FA и выдачи ограниченных токенов доступа."""

    def __init__(self, redis: Redis):
        self.redis = redis

    async def _check_brute_force(self, user_id: str):
        """Проверяет количество неудачных попыток ввода OTP."""
        attempts_key = f"otp_attempts:{user_id}"
        attempts = await self.redis.get(attempts_key)
        
        if attempts and int(attempts) >= MAX_OTP_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много попыток. Запросите код повторно."
            )

    def _generate_jwt(self, data: Dict[str, Any]) -> str:
        """Создает JWT с минимальным набором прав (Scopes) и коротким TTL."""
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode = data.copy()
        to_encode.update({"exp": expire, "iat": datetime.utcnow()})
        return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

    async def verify_otp_and_issue_token(self, user_id: str, provided_otp: str) -> Dict[str, str]:
        """Сверяет OTP в константное время и выдает финальный токен."""
        otp_key = f"otp_value:{user_id}"
        attempts_key = f"otp_attempts:{user_id}"

        # 1. Защита от перебора
        await self._check_brute_force(user_id)

        # 2. Получение эталонного OTP из кэша
        stored_otp = await self.redis.get(otp_key)
        if not stored_otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Код истек или не существует."
            )

        # 3. Сравнение в постоянное время (Constant Time Comparison)
        # Защищает от Side-Channel атак по времени
        is_valid = hmac.compare_digest(provided_otp, stored_otp)

        if not is_valid:
            await self.redis.incr(attempts_key)
            await self.redis.expire(attempts_key, OTP_TTL)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный код подтверждения."
            )

        # 4. Немедленная инвалидация OTP после успеха
        await self.redis.delete(otp_key, attempts_key)

        # 5. Выдача токена с минимально необходимыми правами (Role-Based)
        # Не включаем конфиденциальные данные в Payload
        access_token = self._generate_jwt({
            "sub": user_id,
            "scope": "user:read",  # Минимальные права
            "mfa_verified": True
        })

        return {"access_token": access_token, "token_type": "bearer"}

# --- Эндпоинты ---

@app.post("/verify-otp", status_code=status.HTTP_200_OK)
async def verify_otp(request: VerifyOTPRequest):
    """
    Эндпоинт проверки временного кода. 
    После успеха код удаляется, а пользователю выдается ограниченный JWT.
    """
    service = TwoFactorService(redis_client)
    return await service.verify_otp_and_issue_token(request.user_id, request.otp_code)