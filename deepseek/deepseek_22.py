# app/exceptions/handler.py
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


class APIError(Exception):
    """Базовый класс для всех ошибок API"""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(APIError):
    """Ошибка аутентификации"""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(
            message=message,
            error_code="AUTH_ERROR",
            status_code=status.HTTP_401_UNAUTHORIZED
        )


class AuthorizationError(APIError):
    """Ошибка авторизации"""
    
    def __init__(self, message: str = "Authorization failed"):
        super().__init__(
            message=message,
            error_code="FORBIDDEN",
            status_code=status.HTTP_403_FORBIDDEN
        )


class DatabaseError(APIError):
    """Ошибка базы данных"""
    
    def __init__(self, message: str = "Database error occurred"):
        super().__init__(
            message=message,
            error_code="DB_ERROR",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class NotFoundError(APIError):
    """Ошибка - ресурс не найден"""
    
    def __init__(self, resource: str = "Resource"):
        super().__init__(
            message=f"{resource} not found",
            error_code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND
        )


def setup_exception_handlers(app: FastAPI) -> None:
    """
    Настройка глобальных обработчиков исключений для FastAPI приложения
    """
    
    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, exc: APIError) -> JSONResponse:
        """Обработчик кастомных ошибок API"""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                    "path": request.url.path
                }
            }
        )
    
    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Обработчик ошибок валидации запросов"""
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Validation error in request data",
                    "details": exc.errors(),
                    "path": request.url.path
                }
            }
        )
    
    @app.exception_handler(SQLAlchemyError)
    async def handle_db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """Обработчик ошибок базы данных"""
        # Логируем полную ошибку для отладки
        print(f"Database error: {exc}")
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "DATABASE_ERROR",
                    "message": "Internal database error occurred",
                    "details": {"info": "Please contact support"},
                    "path": request.url.path
                }
            }
        )
    
    @app.exception_handler(Exception)
    async def handle_generic_error(request: Request, exc: Exception) -> JSONResponse:
        """Глобальный обработчик всех неперехваченных исключений"""
        # Логируем полную ошибку для отладки
        print(f"Unhandled error: {exc}")
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Internal server error",
                    "details": {"info": "Please try again later"},
                    "path": request.url.path
                }
            }
        )


# Пример использования
def register_exception_handlers(app: FastAPI) -> None:
    """
    Регистрирует все обработчики исключений в приложении
    """
    setup_exception_handlers(app)