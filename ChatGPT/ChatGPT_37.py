import base64
import json
from dataclasses import dataclass
from typing import Any, Dict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


# ==================================================
# Исключения
# ==================================================

class SignatureError(Exception):
    """Базовая ошибка подписи."""


class SignatureVerificationError(SignatureError):
    """Ошибка проверки подписи."""


# ==================================================
# Доменные модели
# ==================================================

@dataclass(frozen=True)
class FinancialMessage:
    """
    Финансовое сообщение между микросервисами.
    """
    message_type: str
    payload: Dict[str, Any]
    signature: str | None = None


# ==================================================
# Утилиты сериализации
# ==================================================

def canonical_json(data: Dict[str, Any]) -> bytes:
    """
    Детерминированная JSON-сериализация.
    КРИТИЧНО для корректной подписи.
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


# ==================================================
# Подписант (отправитель)
# ==================================================

class FinancialMessageSigner:
    """
    Подписывает финансовые сообщения приватным ключом.
    """

    def __init__(self, private_key_pem: bytes) -> None:
        self._private_key = serialization.load_pem_private_key(
            private_key_pem,
            password=None,
        )

    def sign(self, message: FinancialMessage) -> FinancialMessage:
        """
        Подписывает payload сообщения.
        """
        payload_bytes = canonical_json({
            "message_type": message.message_type,
            "payload": message.payload,
        })

        signature = self._private_key.sign(
            payload_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return FinancialMessage(
            message_type=message.message_type,
            payload=message.payload,
            signature=base64.b64encode(signature).decode(),
        )


# ==================================================
# Верификатор (получатель)
# ==================================================

class FinancialMessageVerifier:
    """
    Проверяет подпись входящих финансовых сообщений.
    """

    def __init__(self, public_key_pem: bytes) -> None:
        self._public_key = serialization.load_pem_public_key(
            public_key_pem
        )

    def verify(self, message: FinancialMessage) -> None:
        """
        Проверяет подпись сообщения.
        """
        if not message.signature:
            raise SignatureVerificationError("Missing signature")

        payload_bytes = canonical_json({
            "message_type": message.message_type,
            "payload": message.payload,
        })

        try:
            self._public_key.verify(
                base64.b64decode(message.signature),
                payload_bytes,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
        except InvalidSignature as exc:
            raise SignatureVerificationError(
                "Invalid message signature"
            ) from exc


# ==================================================
# Генерация ключей (один раз)
# ==================================================

def generate_rsa_keys() -> tuple[bytes, bytes]:
    """
    Генерирует пару RSA-ключей.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return private_pem, public_pem
