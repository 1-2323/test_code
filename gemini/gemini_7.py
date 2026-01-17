import base64
import os
from typing import TypedDict, Union
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

class EncryptedPayload(TypedDict):
    """Структура возвращаемого зашифрованного объекта."""
    iv: str
    ciphertext: str

class VaultService:
    """
    Сервис для безопасного хранения и извлечения API-ключей.
    Реализует шифрование AES-256 (CBC mode) с использованием IV.
    """

    def __init__(self, master_key: str):
        """
        Инициализация сервиса.
        :param master_key: Ключ шифрования в формате base64 (32 байта после декодирования).
        """
        self._key = base64.b64decode(master_key)
        if len(self._key) != 32:
            raise ValueError("Мастер-ключ должен быть длиной 32 байта (AES-256).")
        
        self._backend = default_backend()

    def _apply_padding(self, data: bytes) -> bytes:
        """Добавляет PKCS7 padding, чтобы размер данных был кратен блоку (16 байт)."""
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        return padder.update(data) + padder.finalize()

    def _remove_padding(self, padded_data: bytes) -> bytes:
        """Удаляет PKCS7 padding после дешифровки."""
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        return unpadder.update(padded_data) + unpadder.finalize()

    def encrypt_secret(self, secret_text: str) -> EncryptedPayload:
        """
        Шифрует API-ключ.
        
        Логика работы:
        1. Генерация случайного IV (16 байт).
        2. Добавление отступов (padding) к тексту.
        3. Шифрование алгоритмом AES.
        4. Кодирование результата в Base64 для удобного хранения.
        """
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv), backend=self._backend)
        encryptor = cipher.encryptor()

        # Подготовка данных
        data_bytes = secret_text.encode('utf-8')
        padded_data = self._apply_padding(data_bytes)

        # Шифрование
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        return {
            "iv": base64.b64encode(iv).decode('utf-8'),
            "ciphertext": base64.b64encode(ciphertext).decode('utf-8')
        }

    def decrypt_secret(self, encrypted_data: EncryptedPayload) -> str:
        """
        Расшифровывает API-ключ.
        
        Логика работы:
        1. Декодирование IV и шифротекста из Base64.
        2. Инициализация дешифратора с тем же IV.
        3. Снятие отступов (unpadding) после дешифровки.
        """
        iv = base64.b64decode(encrypted_data['iv'])
        ciphertext = base64.b64decode(encrypted_data['ciphertext'])

        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv), backend=self._backend)
        decryptor = cipher.decryptor()

        # Дешифровка
        padded_result = decryptor.update(ciphertext) + decryptor.finalize()
        
        # Удаление отступов и возврат строки
        result = self._remove_padding(padded_result)
        return result.decode('utf-8')

# --- Пример интеграции и конфигурации ---

if __name__ == "__main__":
    # В реальном приложении этот ключ берется из ENV переменных
    # Сгенерировать новый можно так: base64.b64encode(os.urandom(32))
    CONFIG_MASTER_KEY = "YmFzZTY0LWVuY29kZWQtMzItYnl0ZS1rZXktZXhhbXBsZT0=" # Пример ключа
    
    # 1. Инициализация сервиса
    try:
        vault = VaultService(CONFIG_MASTER_KEY)

        # 2. Шифрование чувствительного ключа
        api_key = "sk-proj-12345ABCDE_SECRET_TOKEN"
        encrypted_obj = vault.encrypt_secret(api_key)
        
        print(f"Зашифрованный объект: {encrypted_obj}")

        # 3. Расшифровка
        decrypted_key = vault.decrypt_secret(encrypted_obj)
        print(f"Расшифрованный ключ: {decrypted_key}")
        
        assert api_key == decrypted_key, "Ошибка: ключи не совпадают!"

    except Exception as e:
        print(f"Критическая ошибка Vault: {e}")