import json
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from typing import Final, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

# --- Конфигурация безопасности ---
# В продакшене ключ должен храниться в KMS или HashiCorp Vault
AUDIT_SECRET_KEY: Final[bytes] = b"system-integrity-verification-key-32-bytes"

class AuditEntry(BaseModel):
    """Строгая схема записи аудита."""
    model_config = ConfigDict(extra='forbid', frozen=True)

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_type: str  # e.g., TRANSACTION_START, BANK_REJECT, STATUS_CHANGE
    user_id: str
    transaction_id: str
    amount: float = Field(..., ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    status: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PaymentAuditor:
    """
    Система аудита безопасности с контролем целостности записей.
    """

    def __init__(self, log_file: str = "payment_audit.log"):
        self.logger = logging.getLogger("PaymentAudit")
        self.logger.setLevel(logging.INFO)
        
        # Настройка файлового хендлера (защищенный append-only лог)
        handler = logging.FileHandler(log_file)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def _calculate_signature(self, payload: str) -> str:
        """Вычисляет HMAC-SHA256 для обеспечения неизменяемости записи."""
        return hmac.new(
            AUDIT_SECRET_KEY,
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def log_event(self, event_type: str, user_id: str, tx_id: str, amount: float, status: str, **kwargs):
        """
        Создает и сохраняет подписанную запись о событии.
        """
        # 1. Создание валидированного объекта события
        entry = AuditEntry(
            event_type=event_type,
            user_id=user_id,
            transaction_id=tx_id,
            amount=amount,
            status=status,
            metadata=kwargs
        )

        # 2. Сериализация в канонический JSON (сортировка ключей важна для подписи)
        canonical_json = entry.model_dump_json(sort_keys=True)

        # 3. Генерация цифровой подписи
        signature = self._calculate_signature(canonical_json)

        # 4. Формирование финальной неизменяемой записи
        audit_record = {
            "payload": json.loads(canonical_json),
            "signature": signature
        }

        # 5. Запись в лог (Append-only)
        self.logger.info(json.dumps(audit_record))

    def verify_log_integrity(self, log_line: str) -> bool:
        """
        Проверяет, не была ли запись изменена после логирования.
        """
        try:
            record = json.loads(log_line)
            payload_str = json.dumps(record["payload"], sort_keys=True)
            expected_sig = self._calculate_signature(payload_str)
            
            return hmac.compare_digest(record["signature"], expected_sig)
        except (KeyError, json.JSONDecodeError):
            return False

# --- Примеры использования ---

auditor = PaymentAuditor()

# Логирование начала транзакции
auditor.log_event(
    event_type="TRANSACTION_START",
    user_id="user_9921",
    tx_id="tx_883002",
    amount=250.00,
    status="PENDING",
    ip_address="192.168.1.50"
)

# Логирование отказа банка
auditor.log_event(
    event_type="BANK_REJECT",
    user_id="user_9921",
    tx_id="tx_883002",
    amount=250.00,
    status="FAILED",
    reason="Insufficient funds",
    bank_code="403"
)