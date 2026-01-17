from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol


# ==================================================
# Исключения
# ==================================================

class SessionSecurityError(Exception):
    """Базовая ошибка безопасности сессии."""


class SessionHijackingDetected(SessionSecurityError):
    """Обнаружена попытка угона сессии."""


# ==================================================
# Доменные модели
# ==================================================

@dataclass(frozen=True)
class SessionMetadata:
    """
    Метаданные сессии, зафиксированные при логине.
    """
    session_id: str
    user_id: int
    ip_address: str
    fingerprint: str
    created_at: datetime


@dataclass(frozen=True)
class RequestContext:
    """
    Контекст текущего HTTP-запроса.
    """
    ip_address: str
    fingerprint: str


# ==================================================
# Контракты
# ==================================================

class SessionMetadataStorage(Protocol):
    """
    Контракт хранилища метаданных сессий (Redis / DB).
    """

    def get(self, session_id: str) -> Optional[SessionMetadata]:
        ...

    def delete(self, session_id: str) -> None:
        ...


class SecurityEventLogger(Protocol):
    """
    Контракт логгера событий безопасности.
    """

    def log(
        self,
        user_id: int,
        session_id: str,
        reason: str,
        detected_at: datetime,
    ) -> None:
        ...


# ==================================================
# Сервис мониторинга сессий
# ==================================================

class SessionSecurityMonitor:
    """
    Проверяет соответствие IP и fingerprint активной сессии.
    """

    def __init__(
        self,
        storage: SessionMetadataStorage,
        event_logger: SecurityEventLogger,
    ) -> None:
        self._storage = storage
        self._logger = event_logger

    # =========================
    # Public API
    # =========================

    def verify_request(
        self,
        session_id: str,
        request_context: RequestContext,
    ) -> None:
        """
        Проверяет, что параметры запроса совпадают
        с данными, зафиксированными при логине.
        """
        metadata = self._storage.get(session_id)

        if not metadata:
            raise SessionSecurityError("Session not found")

        if self._ip_changed(metadata, request_context):
            self._handle_violation(
                metadata,
                reason="IP address mismatch",
            )

        if self._fingerprint_changed(metadata, request_context):
            self._handle_violation(
                metadata,
                reason="Browser fingerprint mismatch",
            )

    # =========================
    # Внутренняя логика
    # =========================

    @staticmethod
    def _ip_changed(
        metadata: SessionMetadata,
        context: RequestContext,
    ) -> bool:
        return metadata.ip_address != context.ip_address

    @staticmethod
    def _fingerprint_changed(
        metadata: SessionMetadata,
        context: RequestContext,
    ) -> bool:
        return metadata.fingerprint != context.fingerprint

    def _handle_violation(
        self,
        metadata: SessionMetadata,
        reason: str,
    ) -> None:
        """
        Реакция на нарушение целостности сессии.
        """
        self._storage.delete(metadata.session_id)

        self._logger.log(
            user_id=metadata.user_id,
            session_id=metadata.session_id,
            reason=reason,
            detected_at=datetime.utcnow(),
        )

        raise SessionHijackingDetected(reason)


# ==================================================
# In-memory реализации (пример)
# ==================================================

class InMemorySessionMetadataStorage:
    """
    Простейшее in-memory хранилище метаданных сессий.
    """

    def __init__(self) -> None:
        self._storage: dict[str, SessionMetadata] = {}

    def get(self, session_id: str) -> Optional[SessionMetadata]:
        return self._storage.get(session_id)

    def delete(self, session_id: str) -> None:
        self._storage.pop(session_id, None)

    def save(self, metadata: SessionMetadata) -> None:
        self._storage[metadata.session_id] = metadata


class ConsoleSecurityEventLogger:
    """
    Пример логгера событий безопасности.
    """

    def log(
        self,
        user_id: int,
        session_id: str,
        reason: str,
        detected_at: datetime,
    ) -> None:
        print(
            f"[SECURITY] user_id={user_id} "
            f"session_id={session_id} "
            f"reason={reason} "
            f"time={detected_at.isoformat()}"
        )


# ==================================================
# Пример использования при логине
# ==================================================

def register_session_metadata(
    storage: InMemorySessionMetadataStorage,
    session_id: str,
    user_id: int,
    ip_address: str,
    fingerprint: str,
) -> None:
    """
    Вызывается при успешном логине пользователя.
    """
    metadata = SessionMetadata(
        session_id=session_id,
        user_id=user_id,
        ip_address=ip_address,
        fingerprint=fingerprint,
        created_at=datetime.utcnow(),
    )
    storage.save(metadata)
