import os
import base64
import logging
from typing import Final, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class VaultSecurityError(Exception):
    """Исключение для ошибок безопасности и шифрования."""
    pass


class VaultService:
    """
    Сервис для безопасного хранения и шифрования секретов.
    Использует AES-256-GCM для обеспечения конфиденциальности и целостности.
    """

    # Длина IV для AES-GCM (стандарт — 12 байт)
    IV_SIZE: Final[int] = 12

    def __init__(self) -> None:
        """
        Инициализация сервиса. Ключ загружается строго из переменных окружения.
        """
        self._logger = logging.getLogger("vault_service")
        self._encryption_key: bytes = self._load_master_key()

    def _load_master_key(self) -> bytes:
        """
        Загружает мастер-ключ из переменной окружения VAULT_MASTER_KEY.
        Ожидается Base64-кодированная строка.
        """
        raw_key_b64: Optional[str] = os.getenv("VAULT_MASTER_KEY")
        
        if not raw_key_b64:
            self._logger.critical("Master key not found in environment variables!")
            raise VaultSecurityError("Configuration Error: VAULT_MASTER_KEY is missing.")

        try:
            key_bytes = base64.b64decode(raw_key_b64)
            # Для AES-256 требуется 32-байтный ключ
            if len(key_bytes) != 32:
                raise VaultSecurityError("Invalid key length. Must be 32 bytes for AES-256.")
            return key_bytes
        except Exception as e:
            raise VaultSecurityError(f"Failed to decode master key: {str(e)}")

    def encrypt_secret(self, plaintext: str) -> str:
        """
        Шифрует строку и возвращает результат в формате Base64.
        Для каждой операции генерируется уникальный вектор инициализации (IV).
        """
        try:
            aesgcm = AESGCM(self._encryption_key)
            # Генерация криптографически стойкого случайного IV
            iv = os.urandom(self.IV_SIZE)
            
            data_bytes = plaintext.encode("utf-8")
            # AES-GCM возвращает ciphertext + tag
            ciphertext = aesgcm.encrypt(iv, data_bytes, None)

            # Результат: IV + CIPHERTEXT (вместе для последующей дешифровки)
            combined_payload = iv + ciphertext
            return base64.b64encode(combined_payload).decode("utf-8")
        
        except Exception as e:
            self._logger.error("Encryption failed (details suppressed for security)")
            raise VaultSecurityError("Failed to encrypt data.")

    def decrypt_secret(self, encrypted_payload_b64: str) -> str:
        """
        Дешифрует Base64-строку. Извлекает IV из начала полезной нагрузки.
        """
        try:
            combined_payload = base64.b64decode(encrypted_payload_b64)
            
            # Извлечение IV и самого шифротекста
            iv = combined_payload[:self.IV_SIZE]
            ciphertext = combined_payload[self.IV_SIZE:]

            aesgcm = AESGCM(self._encryption_key)
            decrypted_bytes = aesgcm.decrypt(iv, ciphertext, None)
            
            return decrypted_bytes.decode("utf-8")
        
        except Exception as e:
            # Важно: логируем только факт ошибки, а не сами данные или IV
            self._logger.error("Decryption failed (possible key mismatch or data corruption)")
            raise VaultSecurityError("Failed to decrypt data: authentication failed.")

    def __repr__(self) -> str:
        """Исключаем вывод секретных полей в отладочную информацию."""
        return f"<VaultService(ready=True)>"