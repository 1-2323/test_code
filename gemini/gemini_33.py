import time
import redis
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

# Настройки безопасности
SECRET_KEY = "YOUR_SUPER_SECRET_JWT_KEY"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
OTP_EXPIRY_SECONDS = 300  # 5 минут

# Подключение к Redis
# Хранит пары {user_id: otp_code}
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

app = FastAPI()

class OTPVerifyRequest(BaseModel):
    user_id: str
    otp_code: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class AuthService:
    """
    Сервис для проверки OTP и выпуска JWT-токенов.
    """

    @staticmethod
    def _generate_jwt(user_id: str) -> str:
        """Создает финальный токен доступа после успешной 2FA."""
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": user_id,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "scope": "access_token"
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def verify_otp_and_issue_token(self, user_id: str, submitted_code: str) -> Optional[str]:
        """
        Сверяет код из Redis. В случае успеха удаляет его и выдает JWT.
        """
        stored_code = r.get(f"otp:{user_id}")

        if not stored_code:
            return None  # Код истек или не создавался

        if stored_code != submitted_code:
            return None  # Неверный код

        # Код верный: удаляем его из кэша (одноразовое использование)
        r.delete(f"otp:{user_id}")
        
        # Генерируем финальный токен
        return self._generate_jwt(user_id)

auth_service = AuthService()

@app.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(request: OTPVerifyRequest):
    """
    Эндпоинт проверки OTP.
    Если код верный — выдает JWT для доступа к защищенным ресурсам.
    """
    token = auth_service.verify_otp_and_issue_token(request.user_id, request.otp_code)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или просроченный код подтверждения",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "access_token": token,
        "token_type": "bearer"
    }

# --- Вспомогательный эндпоинт для теста (эмуляция генерации OTP) ---
@app.post("/mock-send-otp/{user_id}")
async def mock_send_otp(user_id: str):
    import secrets
    otp = str(secrets.randbelow(900000) + 100000) # 6-значный код
    r.setex(f"otp:{user_id}", OTP_EXPIRY_SECONDS, otp)
    return {"message": "Код отправлен", "debug_otp": otp}

if __name__ == "__main__":
    print("OTP Verification Service запущен.")