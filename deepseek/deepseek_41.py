import json
import logging
from typing import Dict, Any, List, Set
from datetime import datetime
import re


class SecureLogger:
    """
    Сервис логирования с автоматической маскировкой чувствительных полей.
    """
    
    # Чувствительные поля, которые нужно маскировать
    SENSITIVE_FIELDS: Set[str] = {
        'password', 'pwd', 'secret', 'token', 
        'cvv', 'cvc', 'credit_card', 'card_number',
        'ssn', 'social_security', 'api_key', 'auth_token'
    }
    
    # Регулярное выражение для поиска чувствительных полей в ключах
    SENSITIVE_PATTERNS: List[str] = [
        r'.*password.*',
        r'.*token.*',
        r'.*secret.*',
        r'.*key.*',
        r'cvv|cvc',
        r'credit.*card',
        r'card.*number',
        r'ssn|social.*security'
    ]
    
    def __init__(
        self, 
        log_file: str = "secure_app.log",
        mask_char: str = "*",
        mask_length: int = 8
    ):
        """
        Инициализация безопасного логгера.
        
        Args:
            log_file: Путь к файлу логов
            mask_char: Символ для маскирования
            mask_length: Длина маски (количество символов)
        """
        self.logger = logging.getLogger("SecureLogger")
        self.logger.setLevel(logging.INFO)
        
        # Обработчик для записи в файл
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        
        self.mask_char = mask_char
        self.mask_length = mask_length
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in self.SENSITIVE_PATTERNS
        ]
    
    def _is_sensitive_field(self, key: str) -> bool:
        """
        Проверяет, является ли поле чувствительным.
        
        Args:
            key: Ключ поля
            
        Returns:
            True если поле чувствительное, иначе False
        """
        key_lower = key.lower()
        
        # Проверка по точному совпадению
        if key_lower in self.SENSITIVE_FIELDS:
            return True
        
        # Проверка по регулярным выражениям
        for pattern in self.compiled_patterns:
            if pattern.match(key_lower):
                return True
        
        return False
    
    def _mask_value(self, value: Any) -> str:
        """
        Маскирует значение чувствительного поля.
        
        Args:
            value: Значение для маскирования
            
        Returns:
            Замаскированное значение
        """
        if not isinstance(value, str):
            value = str(value)
        
        if len(value) <= 3:
            return self.mask_char * self.mask_length
        
        # Маскируем часть значения, оставляя первые и последние символы
        if len(value) > 6:
            masked = value[:2] + self.mask_char * (len(value) - 4) + value[-2:]
        else:
            masked = value[:1] + self.mask_char * (len(value) - 2) + value[-1:]
        
        return masked
    
    def _mask_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Рекурсивно маскирует чувствительные данные в словаре.
        
        Args:
            data: Словарь с данными
            
        Returns:
            Словарь с замаскированными чувствительными данными
        """
        masked_data = {}
        
        for key, value in data.items():
            if self._is_sensitive_field(key):
                masked_data[key] = self._mask_value(value)
            elif isinstance(value, dict):
                masked_data[key] = self._mask_sensitive_data(value)
            elif isinstance(value, list):
                masked_data[key] = [
                    self._mask_sensitive_data(item) if isinstance(item, dict) 
                    else (self._mask_value(item) if self._is_sensitive_field(key) else item)
                    for item in value
                ]
            else:
                masked_data[key] = value
        
        return masked_data
    
    def log_request(self, request_data: Dict[str, Any]) -> None:
        """
        Логирует данные запроса с маскировкой чувствительных полей.
        
        Args:
            request_data: Словарь с данными запроса
        """
        try:
            # Маскируем чувствительные данные
            masked_data = self._mask_sensitive_data(request_data)
            
            # Добавляем временную метку
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "data": masked_data
            }
            
            # Конвертируем в JSON для логирования
            log_message = json.dumps(log_entry, ensure_ascii=False, indent=2)
            
            self.logger.info(f"Request logged:\n{log_message}")
            
        except Exception as e:
            self.logger.error(f"Error logging request: {str(e)}")
            # В случае ошибки логируем без маскировки
            self.logger.error(f"Original request data: {request_data}")


# Пример использования
if __name__ == "__main__":
    secure_logger = SecureLogger()
    
    # Пример данных запроса с чувствительной информацией
    sample_request = {
        "user": "john_doe",
        "password": "SuperSecret123!",
        "email": "john@example.com",
        "credit_card": {
            "number": "4111111111111111",
            "expiry": "12/25",
            "cvv": "123",
            "holder": "John Doe"
        },
        "auth_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "transaction": {
            "amount": 100.50,
            "currency": "USD"
        },
        "api_key": "sk_test_4eC39HqLyjWDarjtT1zdp7dc",
        "tokens": ["access_token_123", "refresh_token_456"]
    }
    
    secure_logger.log_request(sample_request)