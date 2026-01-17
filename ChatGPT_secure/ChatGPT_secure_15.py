import logging
import re
from typing import Iterable, Dict

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


# =========================
# НАСТРОЙКА ЛОГГЕРА
# =========================

logger = logging.getLogger("access")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler("access.log", encoding="utf-8")
formatter = logging.Formatter(
    "%(asctime)s | %(message)s"
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.propagate = False


# =========================
# УТИЛИТЫ ОЧИСТКИ
# =========================

_CONTROL_CHARS_PATTERN = re.compile(r"[\r\n\t\x00-\x1f\x7f]")


def sanitize(value: str) -> str:
    """
    Удаляет переводы строк и управляющие символы.
    """
    return _CONTROL_CHARS_PATTERN.sub("", value)


def mask_value(value: str) -> str:
    """
    Маскирует потенциально чувствительные значения.
    """
    if not value:
        return value
    return "***MASKED***"


# =========================
# MIDDLEWARE
# =========================

class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    Middleware расширенного логирования входящих запросов.
    """

    def __init__(
        self,
        app: ASGIApp,
        logged_headers: Iterable[str],
        sensitive_headers: Iterable[str],
    ) -> None:
        super().__init__(app)
        self._logged_headers = {h.lower() for h in logged_headers}
        self._sensitive_headers = {h.lower() for h in sensitive_headers}

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        method = sanitize(request.method)
        path = sanitize(request.url.path)
        user_agent = sanitize(request.headers.get("user-agent", ""))

        headers_log: Dict[str, str] = {}

        for header in self._logged_headers:
            raw_value = request.headers.get(header)
            if raw_value is None:
                continue

            if header in self._sensitive_headers:
                headers_log[header] = mask_value(raw_value)
            else:
                headers_log[header] = sanitize(raw_value)

        log_message = (
            f"method={method} "
            f"path={path} "
            f"user_agent={user_agent} "
            f"headers={headers_log}"
        )

        logger.info(log_message)
        return response


# =========================
# FASTAPI ПРИЛОЖЕНИЕ
# =========================

app = FastAPI()

app.add_middleware(
    AccessLogMiddleware,
    logged_headers=[
        "x-request-id",
        "x-client-version",
        "authorization",
    ],
    sensitive_headers=[
        "authorization",
        "x-api-key",
    ],
)
