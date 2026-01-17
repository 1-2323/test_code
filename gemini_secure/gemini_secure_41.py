import logging
import json
from typing import Dict, Any, Final, Set

class SecureLogger:
    """
    Сервис безопасного логирования, предотвращающий утечку PII и 
    чувствительных данных (пароли, токены, CVV).
    """

    # Белый список полей, которые разрешено записывать в открытом виде
    ALLOWED_FIELDS: Final[Set[str]] = {
        "user_id", "request_id", "method", "path", "status_code", "timestamp"
    }

    # Поля, которые подлежат обязательной маскировке, если они встретятся
    SENSITIVE_FIELDS: Final[Set[str]] = {
        "password", "cvv", "token", "secret", "card_number", "authorization"
    }

    MASK: Final[str] = "[MASKED]"

    def __init__(self, name: str = "SecureAppLogger"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Настройка вывода в JSON для удобной интеграции с ELK/Splunk
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def _sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Рекурсивно обрабатывает словарь, оставляя только разрешенные поля 
        и маскируя чувствительные.
        """
        clean_data = {}

        for key, value in data.items():
            key_lower = key.lower()

            # 1. Если поле в списке чувствительных — маскируем немедленно
            if key_lower in self.SENSITIVE_FIELDS:
                clean_data[key] = self.MASK
            
            # 2. Если поле в белом списке — сохраняем значение
            elif key_lower in self.ALLOWED_FIELDS:
                if isinstance(value, dict):
                    clean_data[key] = self._sanitize_data(value)
                else:
                    clean_data[key] = value
            
            # 3. Для всех остальных полей (неизвестных) — маскируем на всякий случай
            else:
                clean_data[key] = self.MASK

        return clean_data

    def log_request(self, request_info: Dict[str, Any], level: int = logging.INFO):
        """
        Очищает и записывает данные запроса в лог.
        """
        sanitized = self._sanitize_data(request_info)
        
        # Добавляем метаданные лога
        log_entry = {
            "level": logging.getLevelName(level),
            "event": "inbound_request",
            "data": sanitized
        }
        
        self.logger.log(level, json.dumps(log_entry))

# --- Пример работы ---

# logger = SecureLogger()
# raw_request = {
#     "user_id": "12345",
#     "method": "POST",
#     "password": "my_super_password",
#     "token": "ey123...abc",
#     "unknown_field": "some_data",
#     "cvv": "123",
#     "path": "/api/v1/login"
# }

# logger.log_request(raw_request)
# Результат в логе: 
# {"level": "INFO", "event": "inbound_request", "data": {"user_id": "12345", "method": "POST", "password": "[MASKED]", "token": "[MASKED]", "unknown_field": "[MASKED]", "cvv": "[MASKED]", "path": "/api/v1/login"}}