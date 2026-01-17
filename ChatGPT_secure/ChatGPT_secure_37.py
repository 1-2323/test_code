import json
import time
import hashlib
from typing import Dict, Any
from dataclasses import dataclass
from pathlib import Path

import redis
from pydantic import BaseModel, Field, ValidationError
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)
from cryptography.exceptions import InvalidSignature


# =========================
# CONFIGURATION
# =========================

REDIS_URL = "redis://localhost:6379/0"
REPLAY_TTL_SECONDS = 10 * 60  # 10 minutes

# Пути к ключам (ключи хранятся вне исходного кода)
PRIVATE_KEY_PATH = Path("/secure/keys/sender_private.pem")
PUBLIC_KEY_PATH = Path("/secure/keys/sender_public.pem")


# =========================
# REDIS CLIENT
# =========================

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


# =========================
# MESSAGE SCHEMA
# =========================

class FinancialMessage(BaseModel):
    message_id: str = Field(..., min_length=16, max_length=128)
    timestamp: int
    event_type: str
    payload: Dict[str, Any]


class SignedEnvelope(BaseModel):
    message: FinancialMessage
    signature: str


# =========================
# UTILITIES
# =========================

def canonical_json(data: Dict[str, Any]) -> bytes:
    """
    Каноническое представление JSON для подписи.
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replay_key(message_id: str) -> str:
    return f"replay:{message_id}"


# =========================
# KEY LOADING
# =========================

def load_private_key() -> Ed25519PrivateKey:
    raw = PRIVATE_KEY_PATH.read_bytes()
    return load_pem_private_key(raw, password=None)


def load_public_key() -> Ed25519PublicKey:
    raw = PUBLIC_KEY_PATH.read_bytes()
    return load_pem_public_key(raw)


# =========================
# SENDER
# =========================

class FinancialMessageSigner:
    def __init__(self) -> None:
        self._private_key = load_private_key()

    def sign(self, message: FinancialMessage) -> SignedEnvelope:
        payload = message.model_dump()
        payload_bytes = canonical_json(payload)

        signature = self._private_key.sign(payload_bytes)

        return SignedEnvelope(
            message=message,
            signature=signature.hex(),
        )


# =========================
# RECEIVER
# =========================

class FinancialMessageVerifier:
    def __init__(self) -> None:
        self._public_key = load_public_key()

    def verify_and_accept(self, envelope_raw: Dict[str, Any]) -> FinancialMessage:
        try:
            envelope = SignedEnvelope.model_validate(envelope_raw)
        except ValidationError:
            raise ValueError("Некорректная структура сообщения")

        message = envelope.message

        self._check_replay(message.message_id)
        self._check_timestamp(message.timestamp)

        payload_bytes = canonical_json(message.model_dump())
        signature_bytes = bytes.fromhex(envelope.signature)

        try:
            self._public_key.verify(signature_bytes, payload_bytes)
        except InvalidSignature:
            raise ValueError("Подпись недействительна")

        self._mark_processed(message.message_id)
        return message

    # =========================
    # SECURITY CHECKS
    # =========================

    def _check_replay(self, message_id: str) -> None:
        if redis_client.exists(replay_key(message_id)):
            raise ValueError("Повторная обработка сообщения запрещена")

    def _mark_processed(self, message_id: str) -> None:
        redis_client.setex(
            replay_key(message_id),
            REPLAY_TTL_SECONDS,
            "processed",
        )

    def _check_timestamp(self, timestamp: int) -> None:
        now = int(time.time())
        if abs(now - timestamp) > REPLAY_TTL_SECONDS:
            raise ValueError("Сообщение просрочено")


# =========================
# EXAMPLE USAGE (INTERNAL)
# =========================

def create_and_verify_example() -> None:
    signer = FinancialMessageSigner()
    verifier = FinancialMessageVerifier()

    message = FinancialMessage(
        message_id=sha256_hex(b"unique-seed"),
        timestamp=int(time.time()),
        event_type="payment.executed",
        payload={
            "order_id": 123,
            "amount": "99.50",
            "currency": "USD",
        },
    )

    signed = signer.sign(message)
    verified_message = verifier.verify_and_accept(signed.model_dump())

    assert verified_message.event_type == "payment.executed"
