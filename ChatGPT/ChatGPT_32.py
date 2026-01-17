from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from passlib.context import CryptContext


# =========================
# Исключения
# =========================

class PasswordResetError(Exception):
    """Базовая ошибка сброса пароля."""


class InvalidOrExpiredTokenError(PasswordResetError):
    """Токен недействителен или истёк."""


# =========================
# Доменные модели
# =========================

@dataclass(frozen=True)
class User:
    id: int
    email: str
    password_hash: str


@dataclass(frozen=True)
class PasswordResetToken:
    token: str
    user_id: int
    expires_at: datetime


# =========================
# Контракты репозиториев
# =========================

class UserRepository(Protocol):
    def get_by_id(self, user_id: int) -> Optional[User]:
        ...

    def update_password(self, user_id: int, password_hash: str) -> None:
        ...


class PasswordResetTokenRepository(Protocol):
    def get(self, token: str) -> Optional[PasswordResetToken]:
        ...

    def delete(self, token: str) -> None:
        ...


# =========================
# Хеширование паролей
# =========================

class PasswordHasher:
    """
    Сервис хеширования паролей.
    """
    _context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    @classmethod
    def hash(cls, password: str) -> str:
        return cls._context.hash(password)


# =========================
# Сервис сброса пароля
# =========================

class PasswordResetService:
    """
    Оркестратор подтверждения сброса пароля.
    """

    def __init__(
        self,
        users: UserRepository,
        tokens: PasswordResetTokenRepository,
    ) -> None:
        self._users = users
        self._tokens = tokens

    def confirm_reset(self, token: str, new_password: str) -> None:
        """
        Подтверждает сброс пароля по токену.
        """
        reset_token = self._tokens.get(token)
        if not reset_token:
            raise InvalidOrExpiredTokenError("Invalid token")

        if reset_token.expires_at < datetime.utcnow():
            self._tokens.delete(token)
            raise InvalidOrExpiredTokenError("Token expired")

        user = self._users.get_by_id(reset_token.user_id)
        if not user:
            self._tokens.delete(token)
            raise InvalidOrExpiredTokenError("User not found")

        password_hash = PasswordHasher.hash(new_password)
        self._users.update_password(user.id, password_hash)

        # Токен одноразовый — удаляем после использования
        self._tokens.delete(token)


# =========================
# In-memory реализации (пример)
# =========================

class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[int, User] = {}

    def get_by_id(self, user_id: int) -> Optional[User]:
        return self._users.get(user_id)

    def update_password(self, user_id: int, password_hash: str) -> None:
        user = self._users[user_id]
        self._users[user_id] = User(
            id=user.id,
            email=user.email,
            password_hash=password_hash,
        )


class InMemoryPasswordResetTokenRepository:
    def __init__(self) -> None:
        self._tokens: dict[str, PasswordResetToken] = {}

    def get(self, token: str) -> Optional[PasswordResetToken]:
        return self._tokens.get(token)

    def delete(self, token: str) -> None:
        self._tokens.pop(token, None)


# =========================
# API схема
# =========================

class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8)


# =========================
# FastAPI приложение
# =========================

app = FastAPI(title="Password Reset Service")

user_repo = InMemoryUserRepository()
token_repo = InMemoryPasswordResetTokenRepository()
reset_service = PasswordResetService(user_repo, token_repo)


@app.post("/auth/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
) -> dict:
    """
    Эндпоинт подтверждения сброса пароля.
    """
    try:
        reset_service.confirm_reset(
            token=payload.token,
            new_password=payload.new_password,
        )
    except InvalidOrExpiredTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {"status": "password_updated"}
