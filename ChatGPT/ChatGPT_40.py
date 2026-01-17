from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Protocol


# ==================================================
# Audit Event Types
# ==================================================

class AuditEventType(str, Enum):
    TRANSACTION_STARTED = "transaction_started"
    BANK_DECLINED = "bank_declined"
    STATUS_CHANGED = "status_changed"
    TRANSACTION_COMPLETED = "transaction_completed"


# ==================================================
# Audit Record (immutable)
# ==================================================

@dataclass(frozen=True)
class PaymentAuditRecord:
    """
    Неизменяемая запись аудита безопасности платежей.
    """
    event_type: AuditEventType
    user_id: int
    payment_id: str
    amount: float
    currency: str
    timestamp: datetime
    metadata: Dict[str, Any]


# ==================================================
# Repository Contract
# ==================================================

class AuditRepository(Protocol):
    """
    Контракт хранения audit-событий.
    """

    def save(self, record: PaymentAuditRecord) -> None:
        ...


# ==================================================
# Audit Service
# ==================================================

class SecurityAuditService:
    """
    Сервис аудита безопасности платежного модуля.
    """

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    def log_event(
        self,
        event_type: AuditEventType,
        user_id: int,
        payment_id: str,
        amount: float,
        currency: str,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        record = PaymentAuditRecord(
            event_type=event_type,
            user_id=user_id,
            payment_id=payment_id,
            amount=amount,
            currency=currency,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
        )

        self._repository.save(record)


# ==================================================
# Example Repository (DB / SIEM ready)
# ==================================================

class InMemoryAuditRepository:
    """
    Пример репозитория.
    В проде: PostgreSQL / ClickHouse / Kafka / SIEM.
    """

    def __init__(self) -> None:
        self._storage: list[PaymentAuditRecord] = []

    def save(self, record: PaymentAuditRecord) -> None:
        self._storage.append(record)


# ==================================================
# Payment Service (integration example)
# ==================================================

class PaymentService:
    """
    Пример платёжного сервиса с аудитом.
    """

    def __init__(self, audit_service: SecurityAuditService) -> None:
        self._audit = audit_service

    def process_payment(
        self,
        user_id: int,
        payment_id: str,
        amount: float,
        currency: str,
    ) -> None:
        # Начало транзакции
        self._audit.log_event(
            AuditEventType.TRANSACTION_STARTED,
            user_id,
            payment_id,
            amount,
            currency,
        )

        # Имитация отказа банка
        bank_response = {"code": "BANK_51", "reason": "Insufficient funds"}

        self._audit.log_event(
            AuditEventType.BANK_DECLINED,
            user_id,
            payment_id,
            amount,
            currency,
            metadata=bank_response,
        )

        # Изменение статуса
        self._audit.log_event(
            AuditEventType.STATUS_CHANGED,
            user_id,
            payment_id,
            amount,
            currency,
            metadata={"status": "declined"},
        )
