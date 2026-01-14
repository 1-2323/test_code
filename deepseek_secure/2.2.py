import os
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag
import secrets

class SecretManager:
    """
    Класс для безопасного шифрования и дешифрования секретов с использованием AES-GCM.
    Ключ шифрования берется из переменных окружения.
    """
    
    def __init__(self, env_key_name="APP_ENCRYPTION_KEY"):
        """
        Инициализация SecretManager.
        
        Args:
            env_key_name: Имя переменной окружения, содержащей ключ шифрования
        """
        self.env_key_name = env_key_name
        self.key = self._load_key()
        self.backend = default_backend()
        
    def _load_key(self):
        """
        Загрузка ключа из переменных окружения.
        
        Returns:
            bytes: Ключ шифрования
            
        Raises:
            ValueError: Если ключ не найден в переменных окружения
        """
        key_b64 = os.getenv(self.env_key_name)
        if not key_b64:
            raise ValueError(
                f"Ключ шифрования не найден в переменной окружения '{self.env_key_name}'. "
                "Установите 32-байтовый ключ в формате base64."
            )
        
        try:
            key = base64.b64decode(key_b64)
        except Exception as e:
            raise ValueError(f"Неверный формат ключа: {e}")
            
        if len(key) not in [16, 24, 32]:
            raise ValueError(
                f"Ключ должен быть 16, 24 или 32 байта. Получено: {len(key)} байт"
            )
            
        return key
    
    def encrypt(self, plaintext):
        """
        Шифрование данных с использованием AES-GCM.
        
        Args:
            plaintext: Строка или байты для шифрования
            
        Returns:
            str: Зашифрованные данные в формате base64 (IV + ciphertext + tag)
            
        Raises:
            ValueError: Если plaintext пустой
        """
        if not plaintext:
            raise ValueError("Нельзя шифровать пустые данные")
            
        if isinstance(plaintext, str):
            plaintext = plaintext.encode('utf-8')
        
        # Генерация случайного IV (12 байт рекомендуется для GCM)
        iv = secrets.token_bytes(12)
        
        # Создание шифра
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.GCM(iv),
            backend=self.backend
        )
        encryptor = cipher.encryptor()
        
        # Шифрование данных
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        
        # Получение тега аутентификации
        tag = encryptor.tag
        
        # Объединение IV + ciphertext + tag и кодирование в base64
        encrypted_data = iv + ciphertext + tag
        return base64.b64encode(encrypted_data).decode('utf-8')
    
    def decrypt(self, encrypted_data_b64):
        """
        Дешифрование данных, зашифрованных с помощью AES-GCM.
        
        Args:
            encrypted_data_b64: Зашифрованные данные в формате base64
            
        Returns:
            str: Расшифрованные данные в виде строки
            
        Raises:
            ValueError: Если данные имеют неверный формат
            InvalidTag: Если тег аутентификации неверен (данные повреждены)
        """
        if not encrypted_data_b64:
            raise ValueError("Нельзя дешифровать пустые данные")
        
        try:
            encrypted_data = base64.b64decode(encrypted_data_b64)
        except Exception as e:
            raise ValueError(f"Неверный формат base64: {e}")
        
        # AES-GCM использует IV длиной 12 байт и тег 16 байт
        if len(encrypted_data) < 28:  # 12 (IV) + 16 (минимальный tag)
            raise ValueError("Данные слишком короткие для расшифровки")
        
        # Извлечение компонентов
        iv = encrypted_data[:12]
        tag = encrypted_data[-16:]
        ciphertext = encrypted_data[12:-16]
        
        # Создание шифра для дешифрования
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.GCM(iv, tag),
            backend=self.backend
        )
        decryptor = cipher.decryptor()
        
        try:
            # Дешифрование данных
            decrypted_data = decryptor.update(ciphertext) + decryptor.finalize()
            return decrypted_data.decode('utf-8')
        except InvalidTag as e:
            raise InvalidTag("Ошибка аутентификации. Данные повреждены или ключ неверен.") from e
    
    @staticmethod
    def generate_key(key_size=32):
        """
        Генерация нового ключа шифрования.
        
        Args:
            key_size: Размер ключа в байтах (16, 24 или 32)
            
        Returns:
            str: Ключ в формате base64
            
        Raises:
            ValueError: Если указан недопустимый размер ключа
        """
        if key_size not in [16, 24, 32]:
            raise ValueError("Размер ключа должен быть 16, 24 или 32 байта")
        
        key = secrets.token_bytes(key_size)
        return base64.b64encode(key).decode('utf-8')
    
    def rotate_key(self, new_key_b64):
        """
        Смена ключа шифрования.
        
        Args:
            new_key_b64: Новый ключ в формате base64
            
        Returns:
            bool: True если ключ успешно изменен
        """
        try:
            new_key = base64.b64decode(new_key_b64)
            if len(new_key) not in [16, 24, 32]:
                return False
            
            self.key = new_key
            return True
        except Exception:
            return False