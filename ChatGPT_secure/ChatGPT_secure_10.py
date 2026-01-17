import os
import base64
from typing import Dict, Iterable, Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag


class SensitiveDataProtectorError(Exception):
    pass


class SensitiveDataProtector:
    """
    Сервис защиты чувствительных данных профиля пользователя.

    - Шифрует указанные поля перед сохранением в БД
    - Расшифровывает поля при чтении
    - Использует AES-GCM (аутентифицированное шифрование)
    - Ключ загружается из переменных окружения
    """

    KEY_ENV_NAME = "SENSITIVE_DATA_ENCRYPTION_KEY"
    KEY_SIZE_BYTES = 32          # 256-bit
    IV_SIZE_BYTES = 12           # Рекомендованный nonce для AES-GCM

    def __init__(self, protected_fields: Iterable[str]) -> None:
        self._protected_fields = set(protected_fields)
        self._key: bytes = self._load_key()
        self._cipher = AESGCM(self._key)

    def encrypt_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Шифрует чувствительные поля перед сохранением в БД.

        Возвращает новый словарь, не модифицируя исходный.
        """
        encrypted: Dict[str, Any] = {}

        for field, value in data.items():
            if field in self._protected_fields and value is not None:
                iv, ciphertext = self._encrypt_value(str(value))
                encrypted[field] = {
                    "iv": base64.b64encode(iv).decode("utf-8"),
                    "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
                }
            else:
                encrypted[field] = value

        return encrypted

    def decrypt_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Расшифровывает чувствительные поля после чтения из БД.

        Расшифрованные данные существуют только
        в возвращаемом объекте.
        """
        decrypted: Dict[str, Any] = {}

        for field, value in data.items():
            if field in self._protected_fields and isinstance(value, dict):
                plaintext = self._decrypt_value(
                    iv_b64=value["iv"],
                    ciphertext_b64=value["ciphertext"],
                )
                decrypted[field] = plaintext
            else:
                decrypted[field] = value

        return decrypted

    def _encrypt_value(self, plaintext: str) -> tuple[bytes, bytes]:
        """
        Шифрует одно значение с уникальным IV.
        """
        iv: bytes = os.urandom(self.IV_SIZE_BYTES)
        ciphertext: bytes = self._cipher.encrypt(
            iv,
            plaintext.encode("utf-8"),
            associated_data=None,
        )
        return iv, ciphertext

    def _decrypt_value(self, iv_b64: str, ciphertext_b64: str) -> str:
        """
        Расшифровывает одно значение.
        """
        try:
            iv = base64.b64decode(iv_b64)
            ciphertext = base64.b64decode(ciphertext_b64)

            plaintext_bytes: bytes = self._cipher.decrypt(
                iv,
                ciphertext,
                associated_data=None,
            )
            return plaintext_bytes.decode("utf-8")
        except (InvalidTag, ValueError) as exc:
            raise SensitiveDataProtectorError(
                "Ошибка расшифровки чувствительных данных"
            ) from exc

    def _load_key(self) -> bytes:
        """
        Загружает ключ шифрования из защищённой
        переменной окружения (base64).
        """
        encoded_key = os.getenv(self.KEY_ENV_NAME)

        if not encoded_key:
            raise SensitiveDataProtectorError(
                f"Переменная окружения {self.KEY_ENV_NAME} не задана"
            )

        try:
            key = base64.b64decode(encoded_key)
        except ValueError as exc:
            raise SensitiveDataProtectorError(
                "Некорректный формат ключа шифрования"
            ) from exc

        if len(key) != self.KEY_SIZE_BYTES:
            raise SensitiveDataProtectorError(
                "Неверная длина ключа шифрования"
            )

        return key
