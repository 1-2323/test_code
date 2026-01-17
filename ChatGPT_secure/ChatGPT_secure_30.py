from datetime import timedelta
from typing import Optional

import redis
from fastapi import FastAPI, HTTPException, Response, status
from passlib.context import CryptContext
from pydantic import BaseModel, Field, constr

# =========================
# CONFIGURATION
# =========================

REDIS_URL = "redis://localhost:6379/0"
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 60 * 60

SESSION_COOKIE_NAME = "session_id"

# =========================
# REDIS CLIENT
# =========================

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)

# =========================
# PASSWORD HASHING
# =========================

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
)

# =========================
# MOCK USER STORAGE
# =========================

class UserRecord:
    def __init__(self, user_id: int, username: str, password_hash: str) -> None:
        self.user_id = user_id
        self.username = username
        self.password_hash = password_hash


USER_DB = {
    "admin": UserRecord(
        user_id=1,
        username="admin",
        password_hash=pwd_context.hash("StrongPassword123!"),
    )
}

# =========================
# SCHEMAS
# =========================

class LoginRequest(BaseModel):
    username: constr(min_length=3, max_length=64)
    password: constr(min_length=8, max_length=128)


class LoginResponse(BaseModel):
    user_id: int
    username: str


# =========================
# AUTH SERVICE
# =========================

class AuthService:
    def authenticate(self, username: str, password: str) -> UserRecord:
        self._ensure_not_locked(username)

        user = USER_DB.get(username)
        if not user or not pwd_context.verify(password, user.password_hash):
            self._register_failure(username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверные учетные данные",
            )

        self._reset_failures(username)
        return user

    def _failed_key(self, username: str) -> str:
        return f"auth:failed:{username}"

    def _lock_key(self, username: str) -> str:
        return f"auth:lock:{username}"

    def _register_failure(self, username: str) -> None:
        failures = redis_client.incr(self._failed_key(username))
        redis_client.expire(self._failed_key(username), LOCKOUT_SECONDS)

        if failures >= MAX_FAILED_ATTEMPTS:
            redis_client.setex(
                self._lock_key(username),
                LOCKOUT_SECONDS,
                "locked",
            )

    def _reset_failures(self, username: str) -> None:
        redis_client.delete(self._failed_key(username))
        redis_client.delete(self._lock_key(username))

    def _ensure_not_locked(self, username: str) -> None:
        if redis_client.exists(self._lock_key(username)):
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Аккаунт временно заблокирован",
            )


# =========================
# SESSION MANAGEMENT
# =========================

def create_session(user_id: int) -> str:
    session_id = pwd_context.hash(str(user_id))[-32:]
    redis_client.setex(
        f"session:{session_id}",
        SESSION_TTL_SECONDS,
        user_id,
    )
    return session_id


# =========================
# FASTAPI APP
# =========================

app = FastAPI(title="Auth Service")

auth_service = AuthService()


@app.post(
    "/auth/login",
    response_model=LoginResponse,
)
def login(payload: LoginRequest, response: Response) -> LoginResponse:
    user = auth_service.authenticate(
        username=payload.username,
        password=payload.password,
    )

    session_id = create_session(user.user_id)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL_SECONDS,
        expires=SESSION_TTL_SECONDS,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )

    return LoginResponse(
        user_id=user.user_id,
        username=user.username,
    )
