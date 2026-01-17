from typing import Any, Dict

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException


# =========================
# CUSTOM EXCEPTIONS
# =========================

class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    pass


# =========================
# ERROR RESPONSE MODEL
# =========================

def error_response(
    *,
    error_code: str,
    message: str,
    http_status: int,
) -> JSONResponse:
    """
    Формирует унифицированный JSON-ответ об ошибке
    без технических деталей.
    """
    return JSONResponse(
        status_code=http_status,
        content={
            "error": {
                "code": error_code,
                "message": message,
            }
        },
    )


# =========================
# FASTAPI APP
# =========================

app = FastAPI(
    title="API with Global Exception Handling",
    version="1.0.0",
)


# =========================
# EXCEPTION HANDLERS
# =========================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return error_response(
        error_code="VALIDATION_ERROR",
        message="Некорректные входные данные",
        http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


@app.exception_handler(AuthenticationError)
async def authentication_exception_handler(
    request: Request,
    exc: AuthenticationError,
) -> JSONResponse:
    return error_response(
        error_code="AUTHENTICATION_FAILED",
        message="Ошибка аутентификации",
        http_status=status.HTTP_401_UNAUTHORIZED,
    )


@app.exception_handler(AuthorizationError)
async def authorization_exception_handler(
    request: Request,
    exc: AuthorizationError,
) -> JSONResponse:
    return error_response(
        error_code="ACCESS_DENIED",
        message="Недостаточно прав для выполнения операции",
        http_status=status.HTTP_403_FORBIDDEN,
    )


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(
    request: Request,
    exc: SQLAlchemyError,
) -> JSONResponse:
    return error_response(
        error_code="DATABASE_ERROR",
        message="Ошибка обработки данных",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return error_response(
        error_code="HTTP_ERROR",
        message=exc.detail if isinstance(exc.detail, str) else "Ошибка запроса",
        http_status=exc.status_code,
    )


@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return error_response(
        error_code="INTERNAL_SERVER_ERROR",
        message="Внутренняя ошибка сервера",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# =========================
# SAMPLE ENDPOINT
# =========================

@app.get("/example")
def example_endpoint() -> Dict[str, Any]:
    return {"message": "OK"}
