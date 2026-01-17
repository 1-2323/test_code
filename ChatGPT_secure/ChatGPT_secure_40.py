import json
import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

# =========================
# CONFIGURATION
# =========================

AUDIT_LOG_PATH = Path("payment_audit.log")
HMAC_SECRET = b"load-from-secure-env"  # загружать из переменных окружения
HASH_ALGORITHM = "sha256"

EventType = Literal[
    "transaction_started",
    "bank_declined",
    "status_changed",
]

# =========================
# DATA MODELS
# =========================

@dataclass(frozen=True)
class AuditEvent:
    timestamp: int
    event_type: EventType
    user_id: int
    operation_id: str
    amount: str
    prev_hash: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "user_id": self.user_id,
            "operation_id": self.operation_id,
            "amount": self.amount,
            "prev_hash": self.prev_hash,
        }


# =========================
# HASHING UTILITIES
# =========================

def canonical_json(data: dict) -> bytes:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_record_hash(payload: bytes) -> str:
    return hashlib.new(HASH_ALGORITHM, payload).hexdigest()


def compute_hmac(payload: bytes) -> str:
    return hmac.new(HMAC_SECRET, payload, hashlib.sha256).hexdigest()


# =========================
# AUDIT LOGGER
# =========================

class PaymentAuditLogger:
    """
    Неизменяемый журнал аудита с хэш-цепочкой и HMAC-подписью.
    """

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path
        self._last_hash = self._load_last_hash()

    def log_event(
        self,
        *,
        event_type: EventType,
        user_id: int,
        operation_id: str,
        amount: str,
    ) -> None:
        event = AuditEvent(
            timestamp=int(time.time()),
            event_type=event_type,
            user_id=user_id,
            operation_id=operation_id,
            amount=amount,
            prev_hash=self._last_hash,
        )

        record_bytes = canonical_json(event.to_dict())
        record_hash = compute_record_hash(record_bytes)
        record_hmac = compute_hmac(record_bytes)

        log_entry = {
            "event": event.to_dict(),
            "hash": record_hash,
            "hmac": record_hmac,
        }

        self._append(log_entry)
        self._last_hash = record_hash

    # =========================
    # INTERNALS
    # =========================

    def _append(self, entry: dict) -> None:
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load_last_hash(self) -> str:
        if not self._log_path.exists():
            return "0" * 64

        try:
            with self._log_path.open("r", encoding="utf-8") as f:
                last_line = None
                for last_line in f:
                    pass
                if not last_line:
                    return "0" * 64
                parsed = json.loads(last_line)
                return parsed["hash"]
        except Exception:
            return "0" * 64


# =========================
# PAYMENT MODULE INTEGRATION
# =========================

audit_logger = PaymentAuditLogger(AUDIT_LOG_PATH)


def start_transaction(user_id: int, operation_id: str, amount: str) -> None:
    audit_logger.log_event(
        event_type="transaction_started",
        user_id=user_id,
        operation_id=operation_id,
        amount=amount,
    )


def bank_decline(user_id: int, operation_id: str, amount: str) -> None:
    audit_logger.log_event(
        event_type="bank_declined",
        user_id=user_id,
        operation_id=operation_id,
        amount=amount,
    )


def change_status(user_id: int, operation_id: str, amount: str) -> None:
    audit_logger.log_event(
        event_type="status_changed",
        user_id=user_id,
        operation_id=operation_id,
        amount=amount,
    )
