import os
import base64
from typing import Dict, Any, List, Final, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.exceptions import InvalidTag


class DataIntegrityError(Exception):
    """Выбрасывается, если данные были повреждены или ключ неверен."""
    pass


class SensitiveDataProtector:
    """
    Класс для автоматического шифрования/расшифрования полей профиля.
    Использует AES-GCM для обеспечения аутентифицированного шифрования.
    """

    # Набор полей, подлежащих защите
    PROTECTED_FIELDS: Final[List[str]] = [
        "card_number", 
        "bank_account", 
        "passport_id"
    ]
    
    # Размер вектора инициализации (IV) для GCM
    NONCE_SIZE: Final[int] = 12

    def __init__(self, master_key_b64: str) -> None:
        """
        Инициализация протектора.
        :param master_key_b64: Ключ в формате Base64 (должен быть 32 байта после декодирования).
        """
        try:
            decoded_key = base64.b64decode(master_key_b64)
            if len(decoded_key) != 32:
                raise ValueError("Master key must be 32 bytes for AES-256.")
            self._cipher = AESGCM(decoded_key)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize cipher: {str(e)}")

    def encrypt_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Шифрует чувствительные поля в словаре данных профиля.
        """
        processed_data = profile_data.copy()
        
        for field in self.PROTECTED_FIELDS:
            if field in processed_data and processed_data[field]:
                value_to_encrypt = str(processed_data[field]).encode("utf-8")
                
                # Генерация уникального IV для каждой записи
                nonce = os.urandom(self.NONCE_SIZE)
                
                # Шифрование (результат включает tag аутентификации)
                ciphertext = self._cipher.encrypt(nonce, value_to_encrypt, None)
                
                # Сохраняем как nonce + ciphertext в base64
                combined = base64.b64encode(nonce + ciphertext).decode("utf-8")
                processed_data[field] = combined
                
                # Явное зануление временной переменной для минимизации данных в памяти
                del value_to_encrypt
                
        return processed_data

    def decrypt_profile(self, encrypted_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Расшифровывает чувствительные поля профиля для использования в приложении.
        """
        processed_data = encrypted_data.copy()
        
        for field in self.PROTECTED_FIELDS:
            if field in processed_data and processed_data[field]:
                try:
                    # Декодирование из base64
                    decoded_payload = base64.b64decode(processed_data[field])
                    
                    # Извлечение IV и зашифрованного блока
                    nonce = decoded_payload[:self.NONCE_SIZE]
                    ciphertext = decoded_payload[self.NONCE_SIZE:]
                    
                    # Расшифровка с проверкой целостности
                    decrypted_bytes = self._cipher.decrypt(nonce, ciphertext, None)
                    
                    processed_data[field] = decrypted_bytes.decode("utf-8")
                    
                    # Минимизируем нахождение данных в памяти
                    del decrypted_bytes
                    
                except (InvalidTag, ValueError):
                    raise DataIntegrityError(f"Decryption failed for field '{field}'. Data might be corrupted.")
                except Exception as e:
                    raise DataIntegrityError(f"Unexpected error during decryption: {str(e)}")
                    
        return processed_data

    def __repr__(self) -> str:
        return "<SensitiveDataProtector: AES-256-GCM Enabled>"