import os
import base64
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag


class VaultConfigurationError(Exception):
    """Ошибка конфигурации VaultService."""
    pass


class VaultDecryptionError(Exception):
    """Ошибка расшифровки секрета."""
    pass


class VaultService:
    """
    Сервис безопасного хранения API-ключей.
    Использует AES-GCM с уникальным IV для каждой операции.
    """

    KEY_ENV_NAME = "VAULT_ENCRYPTION_KEY"
    KEY_SIZE_BYTES = 32          # 256-bit key
    IV_SIZE_BYTES = 12           # Рекомендуемый размер nonce для AES-GCM

    def __init__(self) -> None:
        self._key: bytes = self._load_key()
        self._cipher = AESGCM(self._key)

    def encrypt_secret(self, secret: str) -> Tuple[bytes, bytes]:
        """
        Шифрует секрет с использованием уникального IV.

        :param secret: секрет в открытом виде
        :return: кортеж (iv, ciphertext)
        """
        iv: bytes = os.urandom(self.IV_SIZE_BYTES)
        plaintext: bytes = secret.encode("utf-8")

        ciphertext: bytes = self._cipher.encrypt(
            iv,
            plaintext,
            associated_data=None,
        )

        return iv, ciphertext

    def decrypt_secret(self, iv: bytes, ciphertext: bytes) -> str:
        """
        Расшифровывает секрет по IV и зашифрованным данным.

        :param iv: вектор инициализации
        :param ciphertext: зашифрованный секрет
        :return: расшифрованный секрет
        """
        try:
            plaintext: bytes = self._cipher.decrypt(
                iv,
                ciphertext,
                associated_data=None,
            )
        except InvalidTag as exc:
            raise VaultDecryptionError("Не удалось расшифровать секрет") from exc

        return plaintext.decode("utf-8")

    def _load_key(self) -> bytes:
        """
        Загружает ключ шифрования из переменной окружения.
        Ожидается base64-кодированное значение.
        """
        encoded_key = os.getenv(self.KEY_ENV_NAME)

        if not encoded_key:
            raise VaultConfigurationError(
                f"Переменная окружения {self.KEY_ENV_NAME} не задана"
            )

        try:
            key: bytes = base64.b64decode(encoded_key)
        except ValueError as exc:
            raise VaultConfigurationError(
                "Ключ шифрования имеет некорректный формат"
            ) from exc

        if len(key) != self.KEY_SIZE_BYTES:
            raise VaultConfigurationError(
                "Неверная длина ключа шифрования"
            )

        return key
