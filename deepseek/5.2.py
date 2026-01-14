from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from typing import Any, Dict, Optional, Union
import logging
import traceback
import json
from datetime import datetime
from enum import Enum

# Настройка логгера
logger = logging.getLogger(__name__)

class ErrorDetailLevel(str, Enum):
    """Уровень детализации ошибок"""
    MINIMAL = "minimal"
    STANDARD = "standard"
    DETAILED = "detailed"

class ApiErrorResponse(BaseModel):
    """Стандартизированный формат ответа с ошибкой"""
    success: bool = False
    error: str
    message: str
    detail: Optional[Any] = None
    path: Optional[str] = None
    method: Optional[str] = None
    timestamp: Optional[str] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error": "VALIDATION_ERROR",
                "message": "Ошибка валидации входных данных",
                "detail": {
                    "field": "email",
                    "message": "value is not a valid email address"
                },
                "path": "/api/users",
                "method": "POST",
                "timestamp": "2024-01-15T10:30:45.123456",
                "request_id": "req_123456789"
            }
        }

class CustomHTTPException(HTTPException):
    """Кастомное исключение с дополнительной информацией"""
    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        detail: Any = None,
        headers: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.error_code = error_code
        self.message = message
        self.detail = detail

class BusinessException(Exception):
    """Бизнес-исключение для обработки логики приложения"""
    def __init__(
        self,
        error_code: str,
        message: str,
        detail: Any = None,
        status_code: int = 400
    ):
        self.error_code = error_code
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(message)

class ErrorHandlerConfig:
    """Конфигурация обработчика ошибок"""
    def __init__(
        self,
        detail_level: ErrorDetailLevel = ErrorDetailLevel.STANDARD,
        include_traceback: bool = False,
        log_errors: bool = True,
        default_error_message: str = "Внутренняя ошибка сервера",
        enable_request_id: bool = True
    ):
        self.detail_level = detail_level
        self.include_traceback = include_traceback
        self.log_errors = log_errors
        self.default_error_message = default_error_message
        self.enable_request_id = enable_request_id

def setup_global_exception_handlers(
    app: FastAPI,
    config: Optional[ErrorHandlerConfig] = None
):
    """
    Настройка глобальных обработчиков исключений для FastAPI приложения
    
    Параметры:
    - app: FastAPI приложение
    - config: Конфигурация обработчика ошибок
    """
    
    if config is None:
        config = ErrorHandlerConfig()
    
    def extract_request_info(request: Request) -> Dict[str, Any]:
        """Извлечение информации о запросе"""
        request_info = {
            "path": request.url.path,
            "method": request.method,
            "query_params": dict(request.query_params),
            "client": f"{request.client.host}:{request.client.port}" if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }
        
        # Пытаемся получить тело запроса для логирования
        try:
            if hasattr(request.state, "body"):
                request_info["body"] = request.state.body
            elif request.method in ["POST", "PUT", "PATCH"]:
                # Для безопасного логирования - только первые 1000 символов
                body = {}
                for field in await request.form():
                    body[field] = "***"
                request_info["body_preview"] = body
        except Exception:
            pass
            
        return request_info
    
    def create_error_response(
        request: Request,
        error_code: str,
        message: str,
        status_code: int,
        detail: Any = None,
        exc: Optional[Exception] = None
    ) -> JSONResponse:
        """Создание стандартизированного ответа с ошибкой"""
        
        # Базовая информация
        error_response = {
            "success": False,
            "error": error_code,
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Информация о запросе
        if config.detail_level != ErrorDetailLevel.MINIMAL:
            error_response.update({
                "path": request.url.path,
                "method": request.method
            })
        
        # Добавляем детали ошибки в зависимости от уровня детализации
        if detail is not None and config.detail_level in [ErrorDetailLevel.STANDARD, ErrorDetailLevel.DETAILED]:
            error_response["detail"] = detail
        
        # Добавляем traceback только в detailed режиме и если включено
        if (
            config.include_traceback and 
            config.detail_level == ErrorDetailLevel.DETAILED and 
            exc is not None
        ):
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            error_response["traceback"] = tb
        
        # Добавляем request_id если включено
        if config.enable_request_id:
            request_id = request.headers.get("X-Request-ID")
            if request_id:
                error_response["request_id"] = request_id
            
            trace_id = request.headers.get("X-Trace-ID")
            if trace_id:
                error_response["trace_id"] = trace_id
        
        # Определяем заголовки ответа
        headers = {}
        if config.enable_request_id:
            headers["X-Request-ID"] = request.headers.get("X-Request-ID", "")
        
        return JSONResponse(
            status_code=status_code,
            content=error_response,
            headers=headers
        )
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Обработчик стандартных HTTP исключений"""
        
        # Логирование ошибки
        if config.log_errors:
            request_info = extract_request_info(request)
            logger.warning(
                f"HTTP Error {exc.status_code}: {exc.detail}",
                extra={
                    "error_code": "HTTP_EXCEPTION",
                    "status_code": exc.status_code,
                    "request_info": request_info,
                    "headers": dict(exc.headers) if exc.headers else None
                }
            )
        
        # Определяем код ошибки
        error_code = "HTTP_ERROR"
        if exc.status_code == 401:
            error_code = "UNAUTHORIZED"
        elif exc.status_code == 403:
            error_code = "FORBIDDEN"
        elif exc.status_code == 404:
            error_code = "NOT_FOUND"
        elif exc.status_code == 429:
            error_code = "RATE_LIMIT_EXCEEDED"
        
        # Проверяем, является ли исключение кастомным
        if hasattr(exc, "error_code"):
            error_code = exc.error_code
            detail = exc.detail if hasattr(exc, "detail") else None
        else:
            detail = exc.detail
        
        return create_error_response(
            request=request,
            error_code=error_code,
            message=str(detail),
            status_code=exc.status_code,
            detail=detail,
            exc=exc
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Обработчик ошибок валидации запросов FastAPI"""
        
        # Форматируем ошибки валидации
        errors = []
        for error in exc.errors():
            error_detail = {
                "field": " -> ".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"]
            }
            
            # Добавляем input значение если есть
            if "input" in error:
                error_detail["input"] = error["input"]
            
            errors.append(error_detail)
        
        # Логирование
        if config.log_errors:
            request_info = extract_request_info(request)
            logger.warning(
                f"Validation error: {errors}",
                extra={
                    "error_code": "VALIDATION_ERROR",
                    "errors": errors,
                    "request_info": request_info
                }
            )
        
        return create_error_response(
            request=request,
            error_code="VALIDATION_ERROR",
            message="Ошибка валидации входных данных",
            status_code=422,
            detail=errors,
            exc=exc
        )
    
    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(request: Request, exc: ValidationError):
        """Обработчик ошибок валидации Pydantic"""
        
        errors = []
        for error in exc.errors():
            error_detail = {
                "field": " -> ".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"]
            }
            errors.append(error_detail)
        
        if config.log_errors:
            logger.warning(
                f"Pydantic validation error: {errors}",
                extra={
                    "error_code": "PYDANTIC_VALIDATION_ERROR",
                    "errors": errors
                }
            )
        
        return create_error_response(
            request=request,
            error_code="VALIDATION_ERROR",
            message="Ошибка валидации данных",
            status_code=400,
            detail=errors,
            exc=exc
        )
    
    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        """Обработчик бизнес-исключений"""
        
        if config.log_errors:
            request_info = extract_request_info(request)
            logger.warning(
                f"Business error: {exc.message}",
                extra={
                    "error_code": exc.error_code,
                    "detail": exc.detail,
                    "request_info": request_info
                }
            )
        
        return create_error_response(
            request=request,
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
            detail=exc.detail,
            exc=exc
        )
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Глобальный обработчик всех необработанных исключений"""
        
        # Получаем полный traceback для логирования
        error_traceback = traceback.format_exception(type(exc), exc, exc.__traceback__)
        
        # Логируем с полной информацией
        if config.log_errors:
            request_info = extract_request_info(request)
            logger.error(
                f"Unhandled exception: {str(exc)}",
                extra={
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "exception_type": type(exc).__name__,
                    "traceback": error_traceback,
                    "request_info": request_info
                },
                exc_info=True
            )
        
        # Определяем детали для ответа
        detail = None
        if config.detail_level == ErrorDetailLevel.DETAILED:
            detail = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc)
            }
            
            if config.include_traceback:
                detail["traceback"] = error_traceback
        
        return create_error_response(
            request=request,
            error_code="INTERNAL_SERVER_ERROR",
            message=config.default_error_message,
            status_code=500,
            detail=detail,
            exc=exc
        )
    
    # Middleware для добавления информации о запросе
    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        """Middleware для добавления контекста запроса"""
        
        # Сохраняем тело запроса для возможного логирования
        try:
            body = await request.body()
            if body:
                request.state.body = body.decode('utf-8')[:1000]  # Ограничиваем размер
        except Exception:
            pass
        
        # Продолжаем обработку запроса
        response = await call_next(request)
        
        # Добавляем заголовки для трассировки
        if config.enable_request_id:
            request_id = request.headers.get("X-Request-ID")
            if request_id:
                response.headers["X-Request-ID"] = request_id
        
        return response

# Декоратор для удобного использования бизнес-исключений
def raise_business_error(
    error_code: str,
    message: str,
    detail: Any = None,
    status_code: int = 400
):
    """Вспомогательная функция для вызова бизнес-исключений"""
    raise BusinessException(
        error_code=error_code,
        message=message,
        detail=detail,
        status_code=status_code
    )

# Пример использования в приложении FastAPI
def create_app() -> FastAPI:
    """Создание FastAPI приложения с настроенными обработчиками ошибок"""
    
    app = FastAPI(
        title="My API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc"
    )
    
    # Конфигурация обработчика ошибок
    config = ErrorHandlerConfig(
        detail_level=ErrorDetailLevel.STANDARD,
        include_traceback=False,  # В продакшене должно быть False
        log_errors=True,
        default_error_message="Произошла внутренняя ошибка. Пожалуйста, попробуйте позже.",
        enable_request_id=True
    )
    
    # Настройка глобальных обработчиков
    setup_global_exception_handlers(app, config)
    
    # Настройка логгирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Пример маршрутов с обработкой ошибок
    @app.get("/api/users/{user_id}")
    async def get_user(user_id: int):
        """Пример маршрута с проверкой и вызовом ошибки"""
        if user_id < 1:
            raise_business_error(
                error_code="INVALID_USER_ID",
                message="ID пользователя должен быть положительным числом",
                detail={"user_id": user_id},
                status_code=400
            )
        
        # Имитация проверки существования пользователя
        if user_id > 1000:
            raise HTTPException(
                status_code=404,
                detail="Пользователь не найден"
            )
        
        return {"id": user_id, "name": "John Doe"}
    
    @app.post("/api/users")
    async def create_user(user_data: dict):
        """Пример маршрута с автоматической валидацией"""
        # Здесь FastAPI автоматически вызовет RequestValidationError
        # если user_data не соответствует ожидаемой схеме
        return {"success": True, "user": user_data}
    
    @app.get("/api/error-test")
    async def error_test():
        """Маршрут для тестирования обработки ошибок"""
        # Генерация различных типов ошибок
        raise ValueError("Тестовая ошибка сервера")
    
    return app