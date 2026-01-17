import logging
from typing import Union, Dict, Any
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

# Настройка логгера для записи критических ошибок на сервере
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("ExceptionHandler")

class AppError(Exception):
    """Базовый класс для кастомных ошибок приложения."""
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code

class AuthError(AppError):
    """Ошибка аутентификации."""
    def __init__(self, message: str = "Ошибка доступа"):
        super().__init__(code="AUTH_ERROR", message=message, status_code=401)

def create_error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    """Утилита для формирования единообразного JSON-ответа."""
    content = {
        "error": {
            "code": code,
            "message": message,
            "details": details
        }
    }
    return JSONResponse(status_code=status_code, content=content)

def register_exception_handlers(app: FastAPI):
    """
    Регистрация всех обработчиков исключений в приложении.
    """

    @app.exception_handler(AppError)
    async def app_exception_handler(request: Request, exc: AppError):
        """Перехват кастомных бизнес-ошибок."""
        return create_error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """
        Перехват ошибок валидации Pydantic.
        Преобразует сложную структуру Pydantic в понятный список полей.
        """
        errors = []
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            errors.append({"field": field, "message": error["msg"]})
            
        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="Ошибка проверки данных запроса",
            details=errors
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(request: Request, exc: SQLAlchemyError):
        """
        Перехват ошибок базы данных.
        ВАЖНО: Мы логируем детали для админа, но скрываем их от клиента для безопасности.
        """
        logger.error(f"Database Error: {str(exc)}")
        
        # Специальная обработка нарушения уникальности (например, дубликат email)
        if isinstance(exc, IntegrityError):
            return create_error_response(
                status_code=status.HTTP_409_CONFLICT,
                code="DATA_CONFLICT",
                message="Конфликт данных: запись уже существует."
            )

        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="DB_ERROR",
            message="Внутренняя ошибка базы данных. Обратитесь к администратору."
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """Перехват стандартных HTTP ошибок (404, 405 и т.д.)."""
        return create_error_response(
            status_code=exc.status_code,
            code=f"HTTP_{exc.status_code}",
            message=str(exc.detail)
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """
        Глобальный перехватчик (Catch-All).
        Ловит всё, что не попало в другие хендлеры, предотвращая падение сервера.
        """
        logger.critical(f"Unhandled Exception: {exc}", exc_info=True)
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="Непредвиденная ошибка сервера."
        )

# --- Пример интеграции ---

def create_app() -> FastAPI:
    application = FastAPI()
    
    # Подключаем нашу систему обработки ошибок
    register_exception_handlers(application)
    
    @application.get("/users/{user_id}")
    async def get_user(user_id: int):
        # Эмуляция различных ошибок для теста
        if user_id == 0:
            raise AuthError("Доступ к root запрещен")
        if user_id < 0:
            # Вызовет 500 ошибку (Unhandled)
            raise ValueError("Отрицательный ID невозможен")
        return {"id": user_id, "name": "Alice"}

    return application

if __name__ == "__main__":
    import uvicorn
    app = create_app()
    print("Приложение запущено. Попробуйте запросы к /users/0, /users/-1")
    # uvicorn.run(app, host="127.0.0.1", port=8000)