from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Protocol

from passlib.context import CryptContext


# =========================
# Исключения
# =========================

class AuthenticationError(Exception):
    """Базовая ошибка аутентификации."""


class InvalidCredentialsError(AuthenticationError):
    """Неверный логин или пароль."""


class AccountLockedError(AuthenticationError):
    """Аккаунт временно заблокирован."""


# =========================
# Модель пользователя
# =========================

@dataclass(frozen=True)
class User:
    id: int
    username: str
    password_hash: str
    is_active: bool = True


# =========================
# Контракты
# =========================

class UserRepository(Protocol):
    """
    Контракт доступа к пользователям.
    """

    def get_by_username(self, username: str) -> Optional[User]:
        ...


class RedisClient(Protocol):
    """
    Минимальный контракт Redis.
    """

    def get(self, key: str) -> Optional[int]:
        ...

    def incr(self, key: str) -> int:
        ...

    def expire(self, key: str, ttl: int) -> None:
        ...

    def delete(self, key: str) -> None:
        ...


# =========================
# Конфигурация безопасности
# =========================

@dataclass(frozen=True)
class AuthSecurityConfig:
    max_failed_attempts: int = 5
    lockout_seconds: int = 300  # 5 минут


# =========================
# Сервис хеширования паролей
# =========================

class PasswordHasher:
    """
    Сервис хеширования и проверки паролей.
    """

    _context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    @classmethod
    def verify(cls, plain_password: str, password_hash: str) -> bool:
        return cls._context.verify(plain_password, password_hash)


# =========================
# AuthService
# =========================

class AuthService:
    """
    Сервис аутентификации пользователей.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        redis: RedisClient,
        config: AuthSecurityConfig = AuthSecurityConfig(),
    ) -> None:
        self._users = user_repository
        self._redis = redis
        self._config = config

    def authenticate(self, username: str, password: str) -> User:
        """
        Выполняет проверку логина и пароля.

        :raises InvalidCredentialsError
        :raises AccountLockedError
        """
        user = self._users.get_by_username(username)
        if not user or not user.is_active:
            raise InvalidCredentialsError("Invalid username or password")

        self._ensure_not_locked(user)

        if not PasswordHasher.verify(password, user.password_hash):
            self._register_failed_attempt(user)
            raise InvalidCredentialsError("Invalid username or password")

        self._reset_failed_attempts(user)
        return user

    # =========================
    # Внутренняя логика
    # =========================

    def _ensure_not_locked(self, user: User) -> None:
        attempts = self._redis.get(self._attempts_key(user.id)) or 0

        if attempts >= self._config.max_failed_attempts:
            raise AccountLockedError(
                "Account is temporarily locked due to failed login attempts"
            )

    def _register_failed_attempt(self, user: User) -> None:
        key = self._attempts_key(user.id)
        attempts = self._redis.incr(key)

        if attempts == 1:
            self._redis.expire(
                key,
                self._config.lockout_seconds,
            )

    def _reset_failed_attempts(self, user: User) -> None:
        self._redis.delete(self._attempts_key(user.id))

    @staticmethod
    def _attempts_key(user_id: int) -> str:
        return f"auth:failed_attempts:{user_id}"


# =========================
# Пример Redis (Mock)
# =========================

class InMemoryRedis:
    """
    Простейшая имитация Redis (для тестов).
    """

    def __init__(self) -> None:
        self._store: dict[str, int] = {}

    def get(self, key: str) -> Optional[int]:
        return self._store.get(key)

    def incr(self, key: str) -> int:
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    def expire(self, key: str, ttl: int) -> None:
        # TTL не реализован в mock
        pass

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
