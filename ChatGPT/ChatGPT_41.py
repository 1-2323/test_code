import json
import logging
from copy import deepcopy
from typing import Any, Iterable


# ==================================================
# Конфигурация логирования
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

_logger = logging.getLogger("secure_logger")


# ==================================================
# SecureLogger
# ==================================================

class SecureLogger:
    """
    Сервис безопасного логирования.
    Маскирует чувствительные поля в логах.
    """

    DEFAULT_SENSITIVE_FIELDS = {
        "password",
        "passwd",
        "pwd",
        "cvv",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "secret",
        "api_key",
    }

    MASK = "***"

    def __init__(
        self,
        sensitive_fields: Iterable[str] | None = None,
    ) -> None:
        self._sensitive_fields = {
            field.lower()
            for field in (sensitive_fields or self.DEFAULT_SENSITIVE_FIELDS)
        }

    # =========================
    # Public API
    # =========================

    def log_request(
        self,
        message: str,
        data: dict[str, Any],
    ) -> None:
        """
        Логирует данные запроса с маскированием чувствительных полей.
        """
        safe_data = self._mask_data(deepcopy(data))
        _logger.info(
            "%s | payload=%s",
            message,
            json.dumps(safe_data, ensure_ascii=False),
        )

    # =========================
    # Внутренняя логика
    # =========================

    def _mask_data(self, value: Any) -> Any:
        """
        Рекурсивно маскирует чувствительные данные.
        """
        if isinstance(value, dict):
            return {
                key: self.MASK
                if self._is_sensitive(key)
                else self._mask_data(val)
                for key, val in value.items()
            }

        if isinstance(value, list):
            return [self._mask_data(item) for item in value]

        if isinstance(value, tuple):
            return tuple(self._mask_data(item) for item in value)

        return value

    def _is_sensitive(self, field_name: str) -> bool:
        """
        Проверяет, является ли поле чувствительным.
        """
        return field_name.lower() in self._sensitive_fields


