import base64
import os
from dataclasses import dataclass
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# =========================
# Исключения
# =========================

class VaultConfigurationError(Exception):
    """Ошибка конфигурации VaultService."""
    pass


class VaultEncryptionError(Exception):
    """Ошибка при шифровании секрета."""
    pass


class VaultDecryptionError(Exception):
    """Ошибка при расшифровке секрета."""
    pass


# =========================
# Конфигурация
# =========================

@dataclass(frozen=True)
class VaultConfig:
    """
    Конфигурация VaultService.

    encryption_key:
        Ключ шифрования в base64-формате.
        Должен соответствовать длине ключа AES (256 бит).
    """
    encryption_key: str


def load_vault_config() -> VaultConfig:
    """
    Загружает конфигурацию Vault из переменных окружения.
    """
    key: str | None = os.getenv("VAULT_ENCRYPTION_KEY")

    if not key:
        raise VaultConfigurationError(
            "VAULT_ENCRYPTION_KEY is not set in environment"
        )

    return VaultConfig(encryption_key=key)


# =========================
# VaultService
# =========================

class VaultService:
    """
    Сервис для безопасного хранения API-ключей.

    Использует AES-GCM:
    - симметричное шифрование
    - встроенную аутентификацию данных
    - поддержку IV (nonce)
    """

    NONCE_SIZE: int = 12  # Рекомендуемый размер nonce для AES-GCM

    def __init__(self, config: VaultConfig) -> None:
        self._key: bytes = self._decode_key(config.encryption_key)
        self._aesgcm: AESGCM = AESGCM(self._key)

    # =========================
    # Публичные методы
    # =========================

    def encrypt_secret(self, secret: str) -> str:
        """
        Шифрует секрет (API-ключ).

        Алгоритм:
        1. Генерация случайного IV (nonce)
        2. Шифрование секрета
        3. Объединение IV + ciphertext
        4. Кодирование результата в base64

        :param secret: исходный секрет
        :return: зашифрованное значение (base64)
        """
        try:
            nonce: bytes = os.urandom(self.NONCE_SIZE)
            ciphertext: bytes = self._aesgcm.encrypt(
                nonce=nonce,
                data=secret.encode("utf-8"),
                associated_data=None,
            )

            encrypted_payload: bytes = nonce + ciphertext
            return base64.b64encode(encrypted_payload).decode("utf-8")

        except Exception as exc:  # noqa: BLE001
            raise VaultEncryptionError(
                "Failed to encrypt secret"
            ) from exc

    def decrypt_secret(self, encrypted_secret: str) -> str:
        """
        Расшифровывает секрет.

        Алгоритм:
        1. Декодирование base64
        2. Извлечение IV (nonce)
        3. Расшифровка ciphertext
        4. Возврат исходного секрета

        :param encrypted_secret: зашифрованное значение (base64)
        :return: исходный секрет
        """
        try:
            encrypted_payload: bytes = base64.b64decode(encrypted_secret)
            nonce, ciphertext = self._split_payload(encrypted_payload)

            decrypted_bytes: bytes = self._aesgcm.decrypt(
                nonce=nonce,
                data=ciphertext,
                associated_data=None,
            )

            return decrypted_bytes.decode("utf-8")

        except Exception as exc:  # noqa: BLE001
            raise VaultDecryptionError(
                "Failed to decrypt secret"
            ) from exc

    # =========================
    # Внутренние методы
    # =========================

    @staticmethod
    def _decode_key(encoded_key: str) -> bytes:
        """
        Декодирует ключ из base64 и валидирует его длину.
        """
        try:
            key: bytes = base64.b64decode(encoded_key)
        except Exception as exc:  # noqa: BLE001
            raise VaultConfigurationError(
                "Encryption key must be valid base64"
            ) from exc

        if len(key) != 32:
            raise VaultConfigurationError(
                "Encryption key must be 32 bytes (256-bit AES key)"
            )

        return key

    @staticmethod
    def _split_payload(payload: bytes) -> Tuple[bytes, bytes]:
        """
        Разделяет payload на nonce и ciphertext.
        """
        nonce: bytes = payload[:VaultService.NONCE_SIZE]
        ciphertext: bytes = payload[VaultService.NONCE_SIZE:]

        if not nonce or not ciphertext:
            raise VaultDecryptionError("Invalid encrypted payload format")

        return nonce, ciphertext


# =========================
# Пример использования
# =========================

def example_usage() -> None:
    """
    Демонстрация работы VaultService.
    """
    config = load_vault_config()
    vault = VaultService(config)

    api_key = "my-super-secret-api-key"

    encrypted = vault.encrypt_secret(api_key)
    decrypted = vault.decrypt_secret(encrypted)

    assert api_key == decrypted
