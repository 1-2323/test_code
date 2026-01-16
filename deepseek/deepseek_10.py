"""
Модуль для автоматического шифрования/дешифрования
чувствительных данных пользователя перед сохранением в БД.
"""

import json
from typing import Dict, Any, List, Optional, Set, Union
from dataclasses import dataclass, field, asdict
from cryptography.fernet import Fernet
import base64
import os


@dataclass
class ProtectionConfig:
    """Конфигурация защиты чувствительных данных."""
    encryption_key: bytes
    encrypted_fields: Set[str] = field(default_factory=lambda: {
        'credit_card_number',
        'cvv',
        'social_security_number',
        'passport_number',
        'bank_account_number'
    })
    json_fields: Set[str] = field(default_factory=lambda: {
        'additional_sensitive_info'
    })
    
    @classmethod
    def from_env(cls) -> 'ProtectionConfig':
        """
        Создает конфигурацию из переменных окружения.
        
        Returns:
            ProtectionConfig
        """
        # Получаем ключ шифрования из переменных окружения
        key = os.environ.get('ENCRYPTION_KEY')
        
        if not key:
            # Генерируем новый ключ если нет в окружении
            key = Fernet.generate_key()
            print(f"Сгенерирован новый ключ шифрования: {key.decode()}")
        else:
            key = key.encode()
        
        return cls(encryption_key=key)


class EncryptionService:
    """Сервис для шифрования и дешифрования данных."""
    
    def __init__(self, encryption_key: bytes):
        """
        Инициализация сервиса шифрования.
        
        Args:
            encryption_key: Ключ шифрования Fernet
        """
        self.cipher = Fernet(encryption_key)
    
    def encrypt_string(self, plaintext: str) -> str:
        """
        Шифрует строку.
        
        Args:
            plaintext: Исходная строка
            
        Returns:
            Зашифрованная строка в base64
            
        Raises:
            ValueError: Если входные данные некорректны
        """
        if plaintext is None:
            return None
        
        if not isinstance(plaintext, str):
            raise ValueError("Входные данные должны быть строкой")
        
        encrypted_bytes = self.cipher.encrypt(plaintext.encode('utf-8'))
        return base64.b64encode(encrypted_bytes).decode('utf-8')
    
    def decrypt_string(self, encrypted_text: str) -> str:
        """
        Дешифрует строку.
        
        Args:
            encrypted_text: Зашифрованная строка в base64
            
        Returns:
            Расшифрованная строка
            
        Raises:
            ValueError: Если входные данные некорректны или повреждены
        """
        if encrypted_text is None:
            return None
        
        try:
            encrypted_bytes = base64.b64decode(encrypted_text.encode('utf-8'))
            decrypted_bytes = self.cipher.decrypt(encrypted_bytes)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Не удалось дешифровать данные: {str(e)}")
    
    def encrypt_dict(self, data: Dict[str, Any]) -> str:
        """
        Шифрует словарь.
        
        Args:
            data: Словарь для шифрования
            
        Returns:
            Зашифрованный словарь в виде строки base64
        """
        json_str = json.dumps(data, ensure_ascii=False)
        return self.encrypt_string(json_str)
    
    def decrypt_dict(self, encrypted_data: str) -> Dict[str, Any]:
        """
        Дешифрует словарь.
        
        Args:
            encrypted_data: Зашифрованный словарь в виде строки
            
        Returns:
            Расшифрованный словарь
        """
        if encrypted_data is None:
            return {}
        
        json_str = self.decrypt_string(encrypted_data)
        return json.loads(json_str)


class SensitiveDataProtector:
    """
    Класс для автоматической защиты чувствительных данных.
    Прозрачно шифрует/дешифрует указанные поля при сохранении/чтении.
    """
    
    def __init__(self, config: Optional[ProtectionConfig] = None):
        """
        Инициализация защитника данных.
        
        Args:
            config: Конфигурация защиты (если None - загружается из окружения)
        """
        self.config = config or ProtectionConfig.from_env()
        self.encryption_service = EncryptionService(self.config.encryption_key)
    
    def protect_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Шифрует чувствительные данные в словаре.
        
        Args:
            data: Словарь с данными пользователя
            
        Returns:
            Словарь с зашифрованными чувствительными полями
        """
        if not data:
            return data
        
        protected_data = data.copy()
        
        for field_name in self.config.encrypted_fields:
            if field_name in protected_data and protected_data[field_name] is not None:
                try:
                    protected_data[field_name] = self.encryption_service.encrypt_string(
                        str(protected_data[field_name])
                    )
                except Exception as e:
                    print(f"Ошибка при шифровании поля {field_name}: {e}")
        
        for field_name in self.config.json_fields:
            if field_name in protected_data and protected_data[field_name] is not None:
                try:
                    if isinstance(protected_data[field_name], dict):
                        protected_data[field_name] = self.encryption_service.encrypt_dict(
                            protected_data[field_name]
                        )
                except Exception as e:
                    print(f"Ошибка при шифровании JSON поля {field_name}: {e}")
        
        return protected_data
    
    def unprotect_data(self, protected_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Дешифрует защищенные данные в словаре.
        
        Args:
            protected_data: Словарь с зашифрованными данными
            
        Returns:
            Словарь с расшифрованными чувствительными полями
        """
        if not protected_data:
            return protected_data
        
        unprotected_data = protected_data.copy()
        
        for field_name in self.config.encrypted_fields:
            if field_name in unprotected_data and unprotected_data[field_name] is not None:
                try:
                    unprotected_data[field_name] = self.encryption_service.decrypt_string(
                        unprotected_data[field_name]
                    )
                except Exception as e:
                    print(f"Ошибка при дешифровании поля {field_name}: {e}")
                    unprotected_data[field_name] = "[DECRYPTION_ERROR]"
        
        for field_name in self.config.json_fields:
            if field_name in unprotected_data and unprotected_data[field_name] is not None:
                try:
                    unprotected_data[field_name] = self.encryption_service.decrypt_dict(
                        unprotected_data[field_name]
                    )
                except Exception as e:
                    print(f"Ошибка при дешифровании JSON поля {field_name}: {e}")
                    unprotected_data[field_name] = {}
        
        return unprotected_data
    
    def is_protected_field(self, field_name: str) -> bool:
        """
        Проверяет, является ли поле защищенным.
        
        Args:
            field_name: Имя поля
            
        Returns:
            True если поле защищено, иначе False
        """
        return (field_name in self.config.encrypted_fields or 
                field_name in self.config.json_fields)


# Пример интеграции с SQLAlchemy моделью
from sqlalchemy import TypeDecorator, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class EncryptedString(TypeDecorator):
    """
    Пользовательский тип SQLAlchemy для автоматического
    шифрования/дешифрования строковых полей.
    """
    
    impl = String
    cache_ok = True
    
    def __init__(self, length: int = 500, *args, **kwargs):
        """
        Инициализация зашифрованного строкового типа.
        
        Args:
            length: Максимальная длина зашифрованной строки
        """
        super().__init__(length, *args, **kwargs)
        self.protector = SensitiveDataProtector()
    
    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        """
        Вызывается при сохранении значения в БД.
        Шифрует значение если оно не None.
        """
        if value is None:
            return None
        
        # Шифруем только если это чувствительное поле
        # В реальном использовании нужно определить, какое это поле
        try:
            return self.protector.encryption_service.encrypt_string(value)
        except Exception as e:
            print(f"Ошибка при шифровании: {e}")
            return value
    
    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        """
        Вызывается при чтении значения из БД.
        Дешифрует значение если оно не None и похоже на зашифрованное.
        """
        if value is None:
            return None
        
        # Пытаемся дешифровать
        try:
            return self.protector.encryption_service.decrypt_string(value)
        except:
            # Если не удалось дешифровать, возвращаем как есть
            # (может быть незашифрованным или поврежденным)
            return value


# Пример модели пользователя с защищенными полями
from sqlalchemy import Column, Integer, String as SAString, JSON

class ProtectedUser(Base):
    """Модель пользователя с защищенными чувствительными данными."""
    __tablename__ = 'protected_users'
    
    id = Column(Integer, primary_key=True)
    email = Column(SAString(255), nullable=False)
    
    # Защищенные поля
    credit_card_number = Column(EncryptedString(500))
    cvv = Column(EncryptedString(100))
    passport_number = Column(EncryptedString(500))
    
    # JSON поле с дополнительной чувствительной информацией
    additional_info = Column(JSON)
    
    def __init__(self, **kwargs):
        """
        Инициализация пользователя с автоматической защитой данных.
        """
        protector = SensitiveDataProtector()
        
        # Обрабатываем входящие данные
        protected_kwargs = protector.protect_data(kwargs)
        
        # Вызываем конструктор родительского класса
        super().__init__(**protected_kwargs)
    
    def to_dict(self, include_protected: bool = False) -> Dict[str, Any]:
        """
        Преобразует объект в словарь.
        
        Args:
            include_protected: Включать ли защищенные поля (расшифрованные)
            
        Returns:
            Словарь с данными пользователя
        """
        result = {
            'id': self.id,
            'email': self.email,
        }
        
        if include_protected:
            # Создаем защитник для дешифрования
            protector = SensitiveDataProtector()
            
            # Дешифруем защищенные поля
            protected_fields = {
                'credit_card_number': self.credit_card_number,
                'cvv': self.cvv,
                'passport_number': self.passport_number
            }
            
            decrypted_fields = protector.unprotect_data(protected_fields)
            result.update(decrypted_fields)
            
            # Добавляем дополнительную информацию
            if self.additional_info:
                result['additional_info'] = self.additional_info
        
        return result


# Пример использования
if __name__ == "__main__":
    # Устанавливаем ключ шифрования (в реальном проекте через переменные окружения)
    os.environ['ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    
    # Инициализация защитника данных
    protector = SensitiveDataProtector()
    
    # Пример данных пользователя
    user_data = {
        'email': 'user@example.com',
        'credit_card_number': '4111111111111111',
        'cvv': '123',
        'passport_number': 'AB1234567',
        'additional_sensitive_info': {
            'mother_maiden_name': 'Smith',
            'birth_city': 'New York'
        }
    }
    
    print("Исходные данные:")
    print(json.dumps(user_data, indent=2, ensure_ascii=False))
    
    # Шифрование данных
    protected_data = protector.protect_data(user_data)
    print("\nЗащищенные данные:")
    print(json.dumps(protected_data, indent=2, ensure_ascii=False))
    
    # Дешифрование данных
    unprotected_data = protector.unprotect_data(protected_data)
    print("\nВосстановленные данные:")
    print(json.dumps(unprotected_data, indent=2, ensure_ascii=False))
    
    # Проверка целостности
    original_sensitive = {k: v for k, v in user_data.items() 
                         if protector.is_protected_field(k)}
    restored_sensitive = {k: v for k, v in unprotected_data.items() 
                         if protector.is_protected_field(k)}
    
    print(f"\nСовпадение чувствительных данных: {original_sensitive == restored_sensitive}")
    
    # Пример с моделью
    print("\n--- Пример работы с моделью ---")
    
    # Создание объекта пользователя (данные автоматически шифруются)
    user = ProtectedUser(
        email='test@example.com',
        credit_card_number='5555555555554444',
        cvv='456',
        passport_number='CD9876543',
        additional_info={'note': 'VIP client'}
    )
    
    print(f"Email: {user.email}")
    print(f"Зашифрованный номер карты: {user.credit_card_number[:50]}...")
    
    # Получение данных с дешифрованием
    user_dict = user.to_dict(include_protected=True)
    print(f"\nРасшифрованный номер карты: {user_dict.get('credit_card_number')}")