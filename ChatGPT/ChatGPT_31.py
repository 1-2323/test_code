import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol


# =========================
# Исключения
# =========================

class SessionError(Exception):
    """Базовая ошибка работы сессий."""


# =========================
# Контракты
# =========================

class SessionStorage(Protocol):
    """
    Контракт хранилища сессий (например, Redis).
    """

    def save(
        self,
        session_id: str,
        user_id: int,
        expires_at: datetime,
    ) -> None:
        ...

    def delete(self, session_id: str) -> None:
        ...

    def exists(self, session_id: str) -> bool:
        ...


class CookieResponse(Protocol):
    """
    Минимальный контракт HTTP-ответа для установки cookie.
    """

    def set_cookie(
        self,
        key: str,
        value: str,
        max_age: int,
        expires: datetime,
        domain: Optional[str],
        httponly: bool,
        secure: bool,
        samesite: str,
    ) -> None:
        ...

    def delete_cookie(
        self,
        key: str,
        domain: Optional[str],
    ) -> None:
        ...


# =========================
# Конфигурация
# =========================

@dataclass(frozen=True)
class SessionConfig:
    """
    Конфигурация сессии.
    """

    cookie_name: str = "session_id"
    ttl_minutes: int = 60
    domain: Optional[str] = None
    secure: bool = True
    http_only: bool = True
    same_site: str = "Lax"


# =========================
# SessionProvider
# =========================

class SessionProvider:
    """
    Менеджер создания и управления пользовательскими сессиями.
    """

    def __init__(
        self,
        storage: SessionStorage,
        config: SessionConfig = SessionConfig(),
    ) -> None:
        self._storage = storage
        self._config = config

    # =========================
    # Public API
    # =========================

    def create_session(
        self,
        response: CookieResponse,
        user_id: int,
    ) -> str:
        """
        Создаёт новую сессию и устанавливает cookie.
        """
        session_id = self._generate_session_id()
        expires_at = self._expires_at()

        self._storage.save(
            session_id=session_id,
            user_id=user_id,
            expires_at=expires_at,
        )

        response.set_cookie(
            key=self._config.cookie_name,
            value=session_id,
            max_age=self._max_age_seconds(),
            expires=expires_at,
            domain=self._config.domain,
            httponly=self._config.http_only,
            secure=self._config.secure,
            samesite=self._config.same_site,
        )

        return session_id

    def invalidate_session(
        self,
        response: CookieResponse,
        session_id: str,
    ) -> None:
        """
        Инвалидирует сессию при выходе пользователя.
        """
        if session_id:
            self._storage.delete(session_id)

        response.delete_cookie(
            key=self._config.cookie_name,
            domain=self._config.domain,
        )

    # =========================
    # Внутренняя логика
    # =========================

    @staticmethod
    def _generate_session_id() -> str:
        """
        Генерирует криптографически стойкий session_id.
        """
        return secrets.token_urlsafe(32)

    def _expires_at(self) -> datetime:
        """
        Вычисляет дату истечения сессии.
        """
        return datetime.utcnow() + timedelta(
            minutes=self._config.ttl_minutes
        )

    def _max_age_seconds(self) -> int:
        """
        Возвращает TTL cookie в секундах.
        """
        return self._config.ttl_minutes * 60


# =========================
# Пример in-memory хранилища
# =========================

class InMemorySessionStorage:
    """
    Простейшее хранилище сессий (для тестов).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, int] = {}

    def save(
        self,
        session_id: str,
        user_id: int,
        expires_at: datetime,
    ) -> None:
        self._sessions[session_id] = user_id

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions
