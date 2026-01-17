from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError


# =========================
# Модель ответа об ошибке
# =========================

class ErrorResponse(BaseModel):
    """
    Унифицированный формат ошибки REST API.
    """
    error_code: str
    message: str
    details: Optional[Any] = None


# =========================
# Доменные исключения
# =========================

class AuthenticationError(Exception):
    """
    Ошибка аутентификации пользователя.
    """
    pass


class AuthorizationError(Exception):
    """
    Ошибка авторизации пользователя.
    """
    pass


class BusinessLogicError(Exception):
    """
    Ошибка бизнес-логики.
    """
    pass


# =========================
# Фабрика JSON-ответов
# =========================

class ErrorResponseFactory:
    """
    Фабрика для формирования JSON-ответов ошибок.
    """

    @staticmethod
    def create(
        *,
        error_code: str,
        message: str,
        status_code: int,
        details: Optional[Any] = None,
    ) -> JSONResponse:
        payload = ErrorResponse(
            error_code=error_code,
            message=message,
            details=details,
        )
        return JSONResponse(
            status_code=status_code,
            content=payload.dict(),
        )


# =========================
# Регистрация обработчиков
# =========================

def register_exception_handlers(app: FastAPI) -> None:
    """
    Регистрирует глобальные обработчики исключений.
    """

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return ErrorResponseFactory.create(
            error_code="VALIDATION_ERROR",
            message="Invalid request data",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=exc.errors(),
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        request: Request,
        exc: AuthenticationError,
    ) -> JSONResponse:
        return ErrorResponseFactory.create(
            error_code="AUTHENTICATION_ERROR",
            message=str(exc) or "Authentication failed",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(
        request: Request,
        exc: AuthorizationError,
    ) -> JSONResponse:
        return ErrorResponseFactory.create(
            error_code="AUTHORIZATION_ERROR",
            message=str(exc) or "Access denied",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        request: Request,
        exc: SQLAlchemyError,
    ) -> JSONResponse:
        return ErrorResponseFactory.create(
            error_code="DATABASE_ERROR",
            message="Database operation failed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        return ErrorResponseFactory.create(
            error_code="HTTP_ERROR",
            message=exc.detail,
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return ErrorResponseFactory.create(
            error_code="INTERNAL_SERVER_ERROR",
            message="Unexpected server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =========================
# Пример FastAPI-приложения
# =========================

def create_app() -> FastAPI:
    """
    Фабрика FastAPI-приложения с глобальной обработкой ошибок.
    """
    app = FastAPI(title="API with Global Exception Handling")

    register_exception_handlers(app)

    @app.get("/secure")
    def secure_endpoint(authenticated: bool = False) -> Dict[str, str]:
        if not authenticated:
            raise AuthenticationError("User is not authenticated")
        return {"status": "ok"}

    return app


app = create_app()
