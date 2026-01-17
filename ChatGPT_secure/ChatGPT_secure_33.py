import time
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional

import redis
import jwt
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, constr

# =========================
# CONFIGURATION
# =========================

REDIS_URL = "redis://localhost:6379/0"

OTP_TTL_SECONDS = 120
OTP_MAX_ATTEMPTS = 5

JWT_SECRET_KEY = "change-me-via-env"
JWT_ALGORITHM = "HS256"
JWT_TTL_MINUTES = 15

# =========================
# REDIS CLIENT
# =========================

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)

# =========================
# SCHEMAS
# =========================

class OTPVerifyRequest(BaseModel):
    user_id: int
    otp_code: constr(min_length=6, max_length=6, regex=r"^\d{6}$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# =========================
# OTP UTILITIES
# =========================

def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def otp_key(user_id: int) -> str:
    return f"otp:{user_id}"


def otp_attempts_key(user_id: int) -> str:
    return f"otp_attempts:{user_id}"


# =========================
# JWT SERVICE
# =========================

def issue_jwt(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "scope": "user",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=JWT_TTL_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


# =========================
# OTP SERVICE
# =========================

class OTPService:
    def verify(self, *, user_id: int, code: str) -> str:
        self._check_attempts(user_id)

        stored_code = redis_client.get(otp_key(user_id))
        if not stored_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный код",
            )

        if not constant_time_compare(stored_code, code):
            self._register_attempt(user_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный код",
            )

        self._cleanup(user_id)
        return issue_jwt(user_id)

    def _check_attempts(self, user_id: int) -> None:
        attempts = redis_client.get(otp_attempts_key(user_id))
        if attempts and int(attempts) >= OTP_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Превышено количество попыток",
            )

    def _register_attempt(self, user_id: int) -> None:
        key = otp_attempts_key(user_id)
        attempts = redis_client.incr(key)
        if attempts == 1:
            redis_client.expire(key, OTP_TTL_SECONDS)

    def _cleanup(self, user_id: int) -> None:
        redis_client.delete(otp_key(user_id))
        redis_client.delete(otp_attempts_key(user_id))


# =========================
# FASTAPI APPLICATION
# =========================

app = FastAPI(title="2FA OTP Verification")

otp_service = OTPService()


@app.post(
    "/verify-otp",
    response_model=TokenResponse,
)
def verify_otp(payload: OTPVerifyRequest) -> TokenResponse:
    token = otp_service.verify(
        user_id=payload.user_id,
        code=payload.otp_code,
    )
    return TokenResponse(access_token=token)
