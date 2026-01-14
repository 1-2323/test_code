from typing import Dict, Any, Optional, Type
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

app = FastAPI()

class APIError(Exception):
    """Базовый класс для ошибок API"""
    def __init__(
        self,
        message: str = "Произошла ошибка при обработке запроса",
        code: str = "internal_error",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

class ValidationError(APIError):
    """Ошибка валидации"""
    def __init__(self, message: str = "Некорректные данные запроса", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "validation_error", 400, details)

class NotFoundError(APIError):
    """Ресурс не найден"""
    def __init__(self, message: str = "Запрашиваемый ресурс не найден", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "not_found", 404, details)

class UnauthorizedError(APIError):
    """Ошибка авторизации"""
    def __init__(self, message: str = "Требуется авторизация", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, "unauthorized", 401, details)

def create_error_response(
    status_code: int,
    message: str,
    error_code: str,
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Создает структурированный ответ об ошибке"""
    return {
        "error": {
            "code": error_code,
            "message": message,
            "details": details or {}
        }
    }

@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Обработчик для пользовательских ошибок API"""
    logging.error(f"APIError: {exc.code} - {exc.message}", exc_info=False)
    
    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            status_code=exc.status_code,
            message=exc.message,
            error_code=exc.code,
            details=exc.details
        )
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Обработчик ошибок валидации запросов"""
    error_details = {}
    
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error.get("loc", ["body"]))
        error_details[field] = error.get("msg", "Некорректное значение")
    
    logging.warning(f"Validation error: {error_details}")
    
    return JSONResponse(
        status_code=400,
        content=create_error_response(
            status_code=400,
            message="Некорректные данные в запросе",
            error_code="validation_error",
            details={"fields": error_details}
        )
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Обработчик HTTP исключений"""
    
    error_messages = {
        400: "Некорректный запрос",
        401: "Требуется авторизация",
        403: "Доступ запрещен",
        404: "Ресурс не найден",
        405: "Метод не разрешен",
        429: "Слишком много запросов",
        500: "Внутренняя ошибка сервера",
        502: "Ошибка шлюза",
        503: "Сервис временно недоступен",
        504: "Таймаут шлюза"
    }
    
    message = error_messages.get(exc.status_code, "Произошла ошибка")
    
    if isinstance(exc.detail, dict):
        details = exc.detail
    elif isinstance(exc.detail, str):
        details = {"detail": exc.detail}
    else:
        details = {}
    
    logging.warning(f"HTTP {exc.status_code}: {message}")
    
    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            status_code=exc.status_code,
            message=message,
            error_code=f"http_{exc.status_code}",
            details=details
        )
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Глобальный обработчик всех непредвиденных исключений"""
    error_id = f"err_{hash(str(exc)) % 10000:04d}"
    logging.error(f"Unexpected error [{error_id}]: {str(exc)}", exc_info=False)
    
    return JSONResponse(
        status_code=500,
        content=create_error_response(
            status_code=500,
            message="Произошла внутренняя ошибка. Обратитесь в службу поддержки",
            error_code="internal_server_error",
            details={"reference_id": error_id}
        )
    )

# Пример защищенного эндпоинта для демонстрации
@app.get("/items/{item_id}")
async def read_item(item_id: int, q: Optional[str] = None):
    if item_id < 1:
        raise ValidationError("ID должен быть положительным числом")
    
    if item_id > 1000:
        raise NotFoundError(f"Элемент с ID {item_id} не найден")
    
    return {"item_id": item_id, "q": q}

@app.post("/items/")
async def create_item(item: Dict[str, Any]):
    if not item.get("name"):
        raise ValidationError(
            "Поле 'name' обязательно",
            details={"required_fields": ["name"]}
        )
    
    return {"status": "created", "item": item}