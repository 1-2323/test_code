import logging
import uuid
from typing import Any, Dict, Final
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError

# --- Настройка защищенного логирования ---
logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("API_ExceptionHandler")

app = FastAPI()

# --- Константы сообщений ---
GENERIC_ERROR_MSG: Final[str] = "An internal error occurred. Please contact support."
VALIDATION_ERROR_MSG: Final[str] = "The provided data is invalid."

class APIException(Exception):
    """Базовый класс для контролируемых ошибок бизнеса."""
    def __init__(self, message: str, status_code: int = 400, code: str = "BAD_REQUEST"):
        self.message = message
        self.status_code = status_code
        self.code = code

# --- Обработчики ---

@app.exception_handler(APIException)
async def api_exception_handler(request: Request, exc: APIException):
    """Обработка кастомных бизнес-исключений."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "code": exc.code,
            "message": exc.message
        }
    )

@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: Any):
    """Обработка ошибок валидации Pydantic/FastAPI."""
    # Мы не возвращаем 'exc.errors()', так как они могут раскрыть структуру моделей.
    # Вместо этого возвращаем только информацию о невалидных полях без подробностей.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "error",
            "code": "VALIDATION_ERROR",
            "message": VALIDATION_ERROR_MSG
        }
    )

@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, exc: SQLAlchemyError):
    """Перехват ошибок БД (SQLAlchemy)."""
    error_id = uuid.uuid4()
    # Логируем детали ошибки (включая SQL и Traceback) только на сервере
    logger.error(f"Database Error ID {error_id}: {str(exc)}", exc_info=True)
    
    # Клиент получает только ID ошибки для обращения в поддержку
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "code": "DATABASE_CRASH",
            "message": GENERIC_ERROR_MSG,
            "reference": str(error_id)
        }
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Глобальный перехватчик всех остальных необработанных исключений."""
    error_id = uuid.uuid4()
    logger.critical(f"Unhandled Exception ID {error_id}: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": GENERIC_ERROR_MSG,
            "reference": str(error_id)
        }
    )

# --- Пример эндпоинта с ошибкой ---
@app.get("/test-error")
async def trigger_error():
    raise SQLAlchemyError("SELECT * FROM sensitive_table WHERE...") # Это будет скрыто