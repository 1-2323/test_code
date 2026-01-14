import os
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class SecretManager:
    """
    Менеджер для безопасного хранения и обработки секретов (API-ключей)
    с использованием AES-шифрования через Fernet (PBKDF2 + AES-128-CBC).
    """
    
    def __init__(self, env_key_name: str = "APP_SECRET_KEY", salt: Optional[bytes] = None):
        """
        Инициализация менеджера секретов.
        
        Args:
            env_key_name: Имя переменной окружения с мастер-ключом
            salt: Соль для ключевого производного (если None, будет сгенерирована)
        """
        self.env_key_name = env_key_name
        self.salt = salt or os.urandom(16)
        
        # Получаем мастер-ключ из переменных окружения
        self.master_key = self._get_master_key()
        
        # Создаем Fernet объект для шифрования/дешифрования
        self.fernet = self._create_fernet()
    
    def _get_master_key(self) -> str:
        """
        Получение мастер-ключа из переменных окружения.
        
        Returns:
            Мастер-ключ в виде строки
            
        Raises:
            ValueError: Если переменная окружения не установлена
        """
        master_key = os.environ.get(self.env_key_name)
        if not master_key:
            raise ValueError(
                f"Переменная окружения '{self.env_key_name}' не установлена. "
                "Установите её перед использованием SecretManager."
            )
        return master_key
    
    def _create_fernet(self) -> Fernet:
        """
        Создание объекта Fernet для шифрования на основе мастер-ключа.
        
        Returns:
            Объект Fernet для операций шифрования/дешифрования
        """
        # Используем PBKDF2 для получения ключа из пароля
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 32 байта = 256 бит для AES-256
            salt=self.salt,
            iterations=100000,  # Рекомендуемое количество итераций
        )
        
        # Производим ключ из мастер-ключа
        key_material = self.master_key.encode('utf-8')
        key = base64.urlsafe_b64encode(kdf.derive(key_material))
        
        return Fernet(key)
    
    def encrypt_secret(self, plaintext: str) -> str:
        """
        Шифрование секрета (API-ключа).
        
        Args:
            plaintext: Открытый текст для шифрования
            
        Returns:
            Зашифрованная строка в формате base64
        """
        plaintext_bytes = plaintext.encode('utf-8')
        encrypted_bytes = self.fernet.encrypt(plaintext_bytes)
        return base64.urlsafe_b64encode(encrypted_bytes).decode('utf-8')
    
    def decrypt_secret(self, encrypted_text: str) -> str:
        """
        Дешифрование секрета (API-ключа).
        
        Args:
            encrypted_text: Зашифрованная строка в формате base64
            
        Returns:
            Расшифрованный исходный текст
            
        Raises:
            ValueError: Если расшифровка не удалась
        """
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_text.encode('utf-8'))
            decrypted_bytes = self.fernet.decrypt(encrypted_bytes)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Ошибка дешифрования: {str(e)}")
    
    def get_salt(self) -> str:
        """
        Получение соли в виде строки base64.
        
        Returns:
            Соль в формате base64
        """
        return base64.urlsafe_b64encode(self.salt).decode('utf-8')
    
    @staticmethod
    def generate_secure_key(length: int = 32) -> str:
        """
        Генерация безопасного ключа для использования в переменных окружения.
        
        Args:
            length: Длина ключа в байтах
            
        Returns:
            Случайный ключ в виде строки base64
        """
        random_bytes = os.urandom(length)
        return base64.urlsafe_b64encode(random_bytes).decode('utf-8')
    
    def rotate_key(self, new_env_key_name: Optional[str] = None) -> None:
        """
        Смена мастер-ключа.
        
        Args:
            new_env_key_name: Имя новой переменной окружения (если None, используется текущее имя)
        """
        if new_env_key_name:
            self.env_key_name = new_env_key_name
        
        self.master_key = self._get_master_key()
        self.fernet = self._create_fernet()
    
    def verify_encryption(self, test_text: str = "test_verification") -> bool:
        """
        Проверка корректности работы шифрования/дешифрования.
        
        Args:
            test_text: Текст для проверки
            
        Returns:
            True если шифрование/дешифрование работает корректно
        """
        try:
            encrypted = self.encrypt_secret(test_text)
            decrypted = self.decrypt_secret(encrypted)
            return decrypted == test_text
        except Exception:
            return False