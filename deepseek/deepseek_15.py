import logging
import time
from typing import Callable, Dict
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import json

class AdvancedLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для логирования входящих запросов с кастомными заголовками.
    """
    
    def __init__(
        self,
        app,
        log_file: str = "access.log",
        custom_headers: list = None
    ):
        """
        Инициализация middleware.
        
        Args:
            app: FastAPI приложение
            log_file: Путь к файлу лога
            custom_headers: Список кастомных заголовков для логирования
        """
        super().__init__(app)
        self.custom_headers = custom_headers or ["X-User-ID", "X-Request-ID"]
        
        # Настройка логгера
        self.logger = logging.getLogger("access_logger")
        self.logger.setLevel(logging.INFO)
        
        # Форматировщик логов
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": %(message)s}',
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # Обработчик для файла
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Отключаем распространение логов в корневой логгер
        self.logger.propagate = False
    
    def _extract_custom_headers(self, request: Request) -> Dict[str, str]:
        """
        Извлекает значения кастомных заголовков из запроса.
        
        Args:
            request: Входящий HTTP запрос
            
        Returns:
            Словарь с кастомными заголовками
        """
        headers = {}
        for header_name in self.custom_headers:
            header_value = request.headers.get(header_name)
            if header_value:
                headers[header_name] = header_value
        return headers
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Обрабатывает каждый входящий запрос, логирует информацию и передает дальше.
        
        Args:
            request: Входящий HTTP запрос
            call_next: Следующий middleware или обработчик
            
        Returns:
            HTTP ответ
        """
        # Засекаем время выполнения
        start_time = time.time()
        
        # Извлекаем информацию для логирования
        method = request.method
        path = request.url.path
        user_agent = request.headers.get("User-Agent", "Unknown")
        client_ip = request.client.host if request.client else "Unknown"
        
        # Извлекаем кастомные заголовки
        custom_headers = self._extract_custom_headers(request)
        
        # Обрабатываем запрос
        response = await call_next(request)
        
        # Вычисляем время выполнения
        duration = time.time() - start_time
        
        # Формируем запись лога
        log_entry = {
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "duration_seconds": round(duration, 4),
            "client_ip": client_ip,
            "user_agent": user_agent,
            "custom_headers": custom_headers,
            "query_params": str(request.query_params)
        }
        
        # Логируем в формате JSON
        self.logger.info(json.dumps(log_entry))
        
        return response

# Пример использования с FastAPI
app = FastAPI()

# Добавление middleware
app.add_middleware(
    AdvancedLoggingMiddleware,
    log_file="access.log",
    custom_headers=["X-User-ID", "X-Request-ID", "X-API-Key"]
)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/data")
async def create_data():
    return {"message": "Data created"}