import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, field_validator
from dotenv import load_dotenv


# =========================
# LOAD ENVIRONMENT
# =========================

load_dotenv()


# =========================
# CONFIGURATION SCHEMA
# =========================

class CorsSettings(BaseModel):
    """
    Строгая схема конфигурации CORS.
    """

    origins: List[str] = Field(min_length=1)
    methods: List[str] = Field(min_length=1)
    headers: List[str] = Field(min_length=1)

    @field_validator("origins")
    @classmethod
    def validate_origins(cls, values: List[str]) -> List[str]:
        for origin in values:
            if "*" in origin:
                raise ValueError("Использование wildcard в origins запрещено")
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"Некорректный origin: {origin}")
        return values

    @field_validator("methods")
    @classmethod
    def validate_methods(cls, values: List[str]) -> List[str]:
        allowed = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
        for method in values:
            if method.upper() not in allowed:
                raise ValueError(f"Недопустимый HTTP метод: {method}")
        return [m.upper() for m in values]

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, values: List[str]) -> List[str]:
        for header in values:
            if not header.isascii():
                raise ValueError(f"Некорректный заголовок: {header}")
        return values


# =========================
# CONFIG LOADER
# =========================

def load_cors_settings() -> CorsSettings:
    """
    Загружает и валидирует CORS-настройки из окружения.
    """
    try:
        return CorsSettings(
            origins=[
                o.strip()
                for o in os.getenv("CORS_ORIGINS", "").split(",")
                if o.strip()
            ],
            methods=[
                m.strip()
                for m in os.getenv("CORS_METHODS", "").split(",")
                if m.strip()
            ],
            headers=[
                h.strip()
                for h in os.getenv("CORS_HEADERS", "").split(",")
                if h.strip()
            ],
        )
    except ValidationError as exc:
        raise RuntimeError(
            f"Ошибка конфигурации CORS: {exc}"
        ) from exc


# =========================
# FASTAPI INITIALIZATION
# =========================

cors_settings = load_cors_settings()

app = FastAPI(
    title="Configured FastAPI Application",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_settings.origins,
    allow_methods=cors_settings.methods,
    allow_headers=cors_settings.headers,
    allow_credentials=True,
)


# =========================
# HEALTHCHECK
# =========================

@app.get("/health")
def healthcheck() -> dict:
    return {"status": "ok"}
