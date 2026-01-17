import json
import logging
from typing import Any, Dict, Iterable

# =========================
# CONFIGURATION
# =========================

LOG_FILE = "secure_access.log"

# Разрешённые поля, которые вообще могут попасть в лог
ALLOWED_FIELDS: set[str] = {
    "method",
    "path",
    "ip",
    "user_agent",
    "headers",
    "query",
    "status_code",
    "request_id",
}

# Поля, которые подлежат маскированию
SENSITIVE_FIELDS: set[str] = {
    "password",
    "cvv",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
}

MASK = "***"


# =========================
# LOGGER SETUP
# =========================

_logger = logging.getLogger("secure_logger")
_logger.setLevel(logging.INFO)

_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_handler)
_logger.propagate = False


# =========================
# UTILS
# =========================

def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\n", "").replace("\r", "")
    return value


def _mask_sensitive(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: (MASK if k.lower() in SENSITIVE_FIELDS else _mask_sensitive(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_mask_sensitive(v) for v in data]
    return _sanitize_value(data)


def _filter_allowed_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: payload[k] for k in payload if k in ALLOWED_FIELDS}


# =========================
# SECURE LOGGER
# =========================

class SecureLogger:
    """
    Безопасный логгер, предотвращающий утечки чувствительных данных
    """

    @staticmethod
    def log_request(data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return

        filtered = _filter_allowed_fields(data)
        sanitized = _mask_sensitive(filtered)

        try:
            _logger.info(
                json.dumps(
                    sanitized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        except Exception:
            # Никогда не логируем ошибку сериализации с данными запроса
            _logger.info(
                json.dumps({"error": "log_serialization_failed"})
            )
