import logging
import time
from typing import List, Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Настройка системного логгера для записи в файл access.log
logger = logging.getLogger("access_logger")
logger.setLevel(logging.INFO)

# Создание файлового обработчика
file_handler = logging.FileHandler("access.log", encoding="utf-8")
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

class AdvancedLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для расширенного логирования входящих HTTP-запросов.
    Извлекает метаданные запроса и записывает их в изолированный лог-файл.
    """

    def __init__(
        self, 
        app, 
        tracked_headers: List[str] = None
    ):
        """
        :param app: Экземпляр ASGI приложения.
        :param tracked_headers: Список имен кастомных заголовков для логирования.
        """
        super().__init__(app)
        self.tracked_headers = tracked_headers or []

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Обработка цикла запроса: перехват данных до и после выполнения эндпоинта.
        """
        start_time = time.perf_counter()

        # 1. Сбор информации о входящем запросе
        method = request.method
        path = request.url.path
        user_agent = request.headers.get("user-agent", "unknown")
        
        # 2. Сбор значений кастомных заголовков
        custom_header_data = {
            header: request.headers.get(header.lower(), "not_provided")
            for header in self.tracked_headers
        }

        try:
            # Передача запроса следующему обработчику в цепочке
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            # Логирование в случае критического сбоя внутри приложения
            status_code = 500
            raise exc from None
        finally:
            # 3. Расчет времени обработки запроса (мс)
            duration = (time.perf_counter() - start_time) * 1000
            
            # 4. Формирование структурированной строки лога
            log_entry = (
                f"[{method}] Path: {path} | "
                f"Status: {status_code} | "
                f"Time: {duration:.2f}ms | "
                f"UA: {user_agent} | "
                f"CustomHeaders: {custom_header_data}"
            )
            
            logger.info(log_entry)

        return response

# --- Пример интеграции в FastAPI приложение ---

if __name__ == "__main__":
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI(title="LoggingService")

    # Регистрация Middleware
    # Система будет следить за заголовками 'X-Request-ID' и 'X-Device-Info'
    app.add_middleware(
        AdvancedLoggingMiddleware, 
        tracked_headers=["X-Request-ID", "X-Device-Info", "X-User-Role"]
    )

    @app.get("/health")
    async def health_check():
        """Тестовый эндпоинт для проверки работы логгера."""
        return {"status": "operational"}

    # Запуск сервера: uvicorn.run(app, host="127.0.0.1", port=8000)