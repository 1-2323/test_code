"""
Модуль для безопасного хранения API-ключей и других секретов
с использованием шифрования AES-GCM.
"""

import os
import json
from base64 import b64encode, b64decode
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag


class Configuration:
    """Конфигурация для загрузки ключей шифрования."""
    
    @staticmethod
    def get_encryption_key() -> bytes:
        """
        Загружает ключ шифрования из переменных окружения или конфига.
        
        Returns:
            Ключ шифрования в виде байтов
            
        Raises:
            ValueError: Если ключ не найден или некорректен
        """
        # В реальном проекте используйте безопасное хранилище секретов
        key = os.environ.get("ENCRYPTION_KEY")
        
        if not key:
            raise ValueError("ENCRYPTION_KEY не найден в переменных окружения")
        
        # Ключ должен быть 32 байта для AES-256
        key_bytes = key.encode('utf-8')
        
        if len(key_bytes) != 32:
            raise ValueError("Ключ должен быть длиной 32 байта (256 бит)")
        
        return key_bytes
    
    @staticmethod
    def get_key_from_file(filepath: str) -> bytes:
        """
        Альтернативный метод: загрузка ключа из файла.
        
        Args:
            filepath: Путь к файлу с ключом
            
        Returns:
            Ключ шифрования в виде байтов
        """
        with open(filepath, 'rb') as f:
            return f.read(32)


class VaultService:
    """Сервис для шифрования и дешифрования секретов."""
    
    def __init__(self, encryption_key: Optional[bytes] = None):
        """
        Инициализация VaultService.
        
        Args:
            encryption_key: Ключ шифрования (если None, загружается из конфига)
            
        Raises:
            ValueError: Если ключ не найден или некорректен
        """
        self.encryption_key = encryption_key or Configuration.get_encryption_key()
        self.backend = default_backend()
        
        if len(self.encryption_key) not in [16, 24, 32]:
            raise ValueError("Ключ должен быть длиной 16, 24 или 32 байта")
    
    def _generate_iv(self) -> bytes:
        """
        Генерирует случайный вектор инициализации (IV).
        
        Returns:
            IV длиной 16 байт
        """
        return os.urandom(16)
    
    def encrypt_secret(self, plaintext: str, iv: Optional[bytes] = None) -> Dict[str, str]:
        """
        Шифрует секретную строку с использованием AES-GCM.
        
        Args:
            plaintext: Текст для шифрования
            iv: Вектор инициализации (если None, генерируется автоматически)
            
        Returns:
            Словарь с зашифрованными данными и IV в base64
            
        Raises:
            ValueError: Если входные данные некорректны
        """
        if not plaintext:
            raise ValueError("Нельзя шифровать пустую строку")
        
        # Генерируем IV если не предоставлен
        iv = iv or self._generate_iv()
        
        # Подготавливаем текст для шифрования (добавляем padding)
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(plaintext.encode('utf-8')) + padder.finalize()
        
        try:
            # Создаем шифр AES-GCM
            cipher = Cipher(
                algorithms.AES(self.encryption_key),
                modes.GCM(iv),
                backend=self.backend
            )
            
            encryptor = cipher.encryptor()
            
            # Шифруем данные
            ciphertext = encryptor.update(padded_data) + encryptor.finalize()
            
            # Получаем аутентификационный тег
            auth_tag = encryptor.tag
            
            # Кодируем все в base64 для хранения
            return {
                'ciphertext': b64encode(ciphertext).decode('utf-8'),
                'iv': b64encode(iv).decode('utf-8'),
                'auth_tag': b64encode(auth_tag).decode('utf-8')
            }
            
        except Exception as e:
            raise RuntimeError(f"Ошибка при шифровании: {str(e)}")
    
    def decrypt_secret(self, encrypted_data: Dict[str, str]) -> str:
        """
        Дешифрует секретную строку.
        
        Args:
            encrypted_data: Словарь с зашифрованными данными
            
        Returns:
            Расшифрованный текст
            
        Raises:
            ValueError: Если данные некорректны или повреждены
            InvalidTag: Если аутентификация не удалась
        """
        required_keys = ['ciphertext', 'iv', 'auth_tag']
        if not all(key in encrypted_data for key in required_keys):
            raise ValueError(f"Отсутствуют обязательные ключи: {required_keys}")
        
        try:
            # Декодируем данные из base64
            ciphertext = b64decode(encrypted_data['ciphertext'])
            iv = b64decode(encrypted_data['iv'])
            auth_tag = b64decode(encrypted_data['auth_tag'])
            
            # Создаем шифр AES-GCM с аутентификационным тегом
            cipher = Cipher(
                algorithms.AES(self.encryption_key),
                modes.GCM(iv, auth_tag),
                backend=self.backend
            )
            
            decryptor = cipher.decryptor()
            
            # Дешифруем данные
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            
            # Убираем padding
            unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
            plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
            
            return plaintext.decode('utf-8')
            
        except InvalidTag:
            raise InvalidTag("Неверный аутентификационный тег - данные повреждены или ключ неверен")
        except Exception as e:
            raise RuntimeError(f"Ошибка при дешифровании: {str(e)}")
    
    def encrypt_dict(self, data: Dict[str, Any]) -> Dict[str, str]:
        """
        Шифрует словарь с данными.
        
        Args:
            data: Словарь для шифрования
            
        Returns:
            Зашифрованный словарь в виде строки
        """
        json_str = json.dumps(data)
        return self.encrypt_secret(json_str)
    
    def decrypt_dict(self, encrypted_data: Dict[str, str]) -> Dict[str, Any]:
        """
        Дешифрует словарь с данными.
        
        Args:
            encrypted_data: Зашифрованный словарь
            
        Returns:
            Расшифрованный словарь
        """
        json_str = self.decrypt_secret(encrypted_data)
        return json.loads(json_str)


# Пример использования
if __name__ == "__main__":
    # В реальном проекте установите переменную окружения ENCRYPTION_KEY
    os.environ["ENCRYPTION_KEY"] = "ThisIsASampleKeyForDemoPurposes123"
    
    # Инициализация сервиса
    vault = VaultService()
    
    # Шифрование секрета
    api_key = "sk_live_1234567890abcdef"
    encrypted = vault.encrypt_secret(api_key)
    
    print(f"Зашифрованные данные: {encrypted}")
    
    # Дешифрование секрета
    try:
        decrypted = vault.decrypt_secret(encrypted)
        print(f"Расшифрованный секрет: {decrypted}")
        print(f"Совпадают: {decrypted == api_key}")
    except Exception as e:
        print(f"Ошибка дешифрования: {e}")