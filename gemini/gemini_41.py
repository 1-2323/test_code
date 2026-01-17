import json
import logging
import re
from typing import Any, Dict, List, Union

class SecureLogger:
    """
    Логгер, обеспечивающий защиту персональных данных (PII) 
    путем автоматического маскирования чувствительных полей.
    """

    # Список ключей, значения которых подлежат маскировке
    SENSITIVE_KEYS = {
        "password", "cvv", "cvc", "token", "access_token", 
        "secret", "api_key", "card_number", "auth_header"
    }

    def __init__(self, name: str = "SecureLogger", log_file: str = "secure_app.log"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Настройка вывода в файл и консоль
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def _mask_value(self, value: Any) -> str:
        """Логика маскирования: оставляет видимыми только части данных."""
        str_val = str(value)
        if len(str_val) <= 4:
            return "****"
        # Показываем только первые 2 и последние 2 символа для удобства отладки
        return f"{str_val[:2]}****{str_val[-2:]}"

    def _process_data(self, data: Any) -> Any:
        """
        Рекурсивно обходит структуру данных и заменяет значения 
        чувствительных ключей на маскированные.
        """
        if isinstance(data, dict):
            return {
                k: (self._mask_value(v) if k.lower() in self.SENSITIVE_KEYS else self._process_data(v))
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._process_data(item) for item in data]
        return data

    def log_request(self, metadata: Dict[str, Any], message: str = "Incoming request"):
        """Записывает очищенные данные в лог."""
        secure_data = self._process_data(metadata)
        # Превращаем в JSON-строку для удобства чтения в логах
        log_entry = f"{message} | Data: {json.dumps(secure_data, ensure_ascii=False)}"
        self.logger.info(log_entry)

# --- Пример использования ---

if __name__ == "__main__":
    logger = SecureLogger()

    # Имитация данных запроса с вложенными структурами
    request_data = {
        "user_id": 1024,
        "action": "payment_process",
        "auth": {
            "token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "session_id": "sess_998877"
        },
        "payment_info": {
            "card_number": "4242424242424242",
            "cvv": 123,
            "amount": 500.0
        },
        "credentials": {
            "login": "admin",
            "password": "SuperSecretPassword2026"
        }
    }

    print("Запись данных в лог...")
    logger.log_request(request_data, "Оформление заказа")
    
    # Проверка содержимого файла (имитация)
    with open("secure_app.log", "r") as f:
        print("\nПоследняя запись в логе:")
        print(f.readlines()[-1])