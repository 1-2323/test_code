import logging
import re
import time
from typing import Callable, Final, List, Set
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SafeAccessLoggerMiddleware(BaseHTTPMiddleware):
    """
    Middleware для безопасного логирования HTTP-запросов.
    Обеспечивает защиту от Log Injection и утечки конфиденциальных данных.
    """

    # Список заголовков, значения которых нужно маскировать
    SENSITIVE_HEADERS: Final[Set[str]] = {
        "authorization", 
        "proxy-authorization", 
        "x-api-key", 
        "cookie", 
        "set-cookie"
    }

    # Регулярное выражение для удаления управляющих символов и переносов строк
    # Оставляем только печатные символы для предотвращения манипуляции логами
    CONTROL_CHARS_RE: Final[re.Pattern] = re.compile(r"[\x00-\x1f\x7f-\x9f]")

    def __init__(self, app: FastAPI, log_file: str = "access.log"):
        super().__init__(app)
        self._setup_logger(log_file)

    def _setup_logger(self, log_file: str) -> None:
        """Настройка файлового логгера."""
        self.logger = logging.getLogger("AccessLogger")
        self.logger.setLevel(logging.INFO)
        
        # Чтобы логи не дублировались в консоль основного приложения
        self.logger.propagate = False
        
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter('%(message)s')  # Формат задаем вручную в коде
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def _sanitize(self, text: str) -> str:
        """
        Удаляет управляющие символы и заменяет переносы строк пробелами.
        Предотвращает атаку Log Injection.
        """
        if not text:
            return ""
        # Удаляем управляющие последовательности и CRLF
        clean_text = self.CONTROL_CHARS_RE.sub("", text)
        return clean_text.replace("\n", " ").replace("\r", " ").strip()

    def _get_safe_headers(self, headers: Dict) -> str:
        """
        Извлекает заголовки, маскируя чувствительные данные.
        """
        header_parts = []
        for key, value in headers.items():
            key_lower = key.lower()
            safe_key = self._sanitize(key)
            
            if key_lower in self.SENSITIVE_HEADERS:
                safe_value = "***"
            else:
                safe_value = self._sanitize(value)
                
            header_parts.append(f"{safe_key}: {safe_value}")
        
        return " | ".join(header_parts)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Основной цикл обработки запроса middleware.
        """
        start_time = time.time()
        
        # Сбор данных до выполнения запроса
        method = self._sanitize(request.method)
        path = self._sanitize(str(request.url.path))
        user_agent = self._sanitize(request.headers.get("user-agent", "unknown"))
        client_ip = request.client.host if request.client else "unknown"
        
        # Обработка кастомных заголовков
        safe_headers = self._get_safe_headers(request.headers)

        # Выполнение самого запроса
        response = await call_next(request)
        
        process_time = f"{(time.time() - start_time) * 1000:.2f}ms"
        status_code = response.status_code

        # Формирование финальной строки лога
        log_entry = (
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"IP: {client_ip} | {method} {path} | Status: {status_code} | "
            f"Time: {process_time} | UA: {user_agent} | Headers: [{safe_headers}]"
        )

        self.logger.info(log_entry)
        
        return response

# --- Подключение к FastAPI ---

app = FastAPI()
app.add_middleware(SafeAccessLoggerMiddleware, log_file="access_security.log")

@app.get("/")
async def root():
    return {"status": "ok"}