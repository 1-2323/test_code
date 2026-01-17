import structlog
import uuid
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# 1. Определяем типы критических событий
class AuditEvent(str, Enum):
    TRANSACTION_STARTED = "PAYMENT_START"
    BANK_REJECTED = "BANK_DECLINED"
    STATUS_CHANGED = "STATUS_UPDATE"
    FRAUD_ALERT = "FRAUD_DETECTED"

# 2. Настройка структурированного логирования
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer() # Логи в формате JSON для машин
    ],
    logger_factory=structlog.WriteLoggerFactory(
        file=open("payment_audit.log", "a", encoding="utf-8")
    )
)

audit_logger = structlog.get_logger("payment_security_audit")

class PaymentAuditor:
    """
    Сервис аудита безопасности платежных операций.
    """

    @staticmethod
    def log_event(
        event_type: AuditEvent,
        user_id: int,
        amount: float,
        transaction_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ):
        """
        Записывает критическое событие в журнал аудита.
        """
        tx_id = transaction_id or f"TX-{uuid.uuid4().hex[:8].upper()}"
        
        # Формируем контекст события
        log_data = {
            "event": event_type.value,
            "user_id": user_id,
            "amount": amount,
            "transaction_id": tx_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        if metadata:
            log_data.update(metadata)

        # Логируем с соответствующим уровнем важности
        if event_type == AuditEvent.BANK_REJECTED:
            audit_logger.warning("payment_issue", **log_data)
        elif event_type == AuditEvent.FRAUD_ALERT:
            audit_logger.critical("security_breach", **log_data)
        else:
            audit_logger.info("payment_step", **log_data)
        
        return tx_id

# --- Пример использования в платежном модуле ---

if __name__ == "__main__":
    auditor = PaymentAuditor()
    user_id = 777
    payment_amount = 15000.50

    # Шаг 1: Начало транзакции
    tx_id = auditor.log_event(
        AuditEvent.TRANSACTION_STARTED, 
        user_id, 
        payment_amount
    )

    # Шаг 2: Симуляция отказа банка
    auditor.log_event(
        AuditEvent.BANK_REJECTED,
        user_id,
        payment_amount,
        transaction_id=tx_id,
        metadata={"reason": "Insufficient funds", "bank_code": "51"}
    )

    # Шаг 3: Изменение статуса
    auditor.log_event(
        AuditEvent.STATUS_CHANGED,
        user_id,
        payment_amount,
        transaction_id=tx_id,
        metadata={"old_status": "pending", "new_status": "failed"}
    )

    print(f"Аудит завершен. Данные транзакции {tx_id} сохранены в payment_audit.log")