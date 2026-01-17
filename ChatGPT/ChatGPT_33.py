from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol

import jwt
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field


# =========================
# Исключения
# =========================

class TwoFactorAuthError(Exception):
    """Базовая ошибка 2FA."""


class InvalidOtpError(TwoFactorAuthError):
    """Неверный или истёкший OTP-код."""


# =========================
# Доменные модели
# =========================

@dataclass(frozen=True)
class OtpCode:
    user_id: int
    code: str
    expires_at: datetime


# =========================
# Контракты
# =========================

class OtpCache(Protocol):
    """
    Контракт кэша OTP (Redis-ready).
    """

    def get(self, user_id: int) -> Optional[OtpCode]:
        ...

    def delete(self, user_id: int) -> None:
        ...


# =========================
# JWT Provider
# =========================

class JwtProvider:
    """
    Генератор JWT-токенов доступа.
    """

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        ttl_minutes: int = 30,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._ttl = ttl_minutes

    def generate(self, user_id: int) -> str:
        payload = {
            "sub": str(user_id),
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(minutes=self._ttl),
        }
        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)


# =========================
# Сервис 2FA
# =========================

class TwoFactorAuthService:
    """
    Сервис проверки OTP и выдачи JWT.
    """

    def __init__(
        self,
        otp_cache: OtpCache,
        jwt_provider: JwtProvider,
    ) -> None:
        self._otp_cache = otp_cache
        self._jwt_provider = jwt_provider

    def verify_otp(self, user_id: int, otp_code: str) -> str:
        """
        Проверяет OTP и возвращает JWT-токен.
        """
        cached = self._otp_cache.get(user_id)

        if not cached:
            raise InvalidOtpError("OTP code not found")

        if cached.expires_at < datetime.utcnow():
            self._otp_cache.delete(user_id)
            raise InvalidOtpError("OTP code expired")

        if cached.code != otp_code:
            raise InvalidOtpError("Invalid OTP code")

        # OTP одноразовый
        self._otp_cache.delete(user_id)

        return self._jwt_provider.generate(user_id)


# =========================
# In-memory OTP cache (пример)
# =========================

class InMemoryOtpCache:
    """
    Простейшая in-memory реализация OTP-кэша.
    """

    def __init__(self) -> None:
        self._storage: dict[int, OtpCode] = {}

    def get(self, user_id: int) -> Optional[OtpCode]:
        return self._storage.get(user_id)

    def delete(self, user_id: int) -> None:
        self._storage.pop(user_id, None)


# =========================
# API схема
# =========================

class VerifyOtpRequest(BaseModel):
    user_id: int
    otp_code: str = Field(..., min_length=4, max_length=8)


class VerifyOtpResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# =========================
# FastAPI приложение
# =========================

app = FastAPI(title="Two-Factor Authentication Service")

otp_cache = InMemoryOtpCache()
jwt_provider = JwtProvider(secret_key="SUPER_SECRET_KEY")
two_factor_service = TwoFactorAuthService(otp_cache, jwt_provider)


@app.post(
    "/verify-otp",
    response_model=VerifyOtpResponse,
)
def verify_otp(payload: VerifyOtpRequest) -> VerifyOtpResponse:
    """
    Эндпоинт проверки OTP и выдачи JWT.
    """
    try:
        token = two_factor_service.verify_otp(
            user_id=payload.user_id,
            otp_code=payload.otp_code,
        )
    except InvalidOtpError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return VerifyOtpResponse(access_token=token)
