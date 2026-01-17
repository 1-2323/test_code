import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseSettings, Field


# =========================
# Конфигурация приложения
# =========================

class AppSettings(BaseSettings):
    """
    Настройки приложения, загружаемые из .env файла.
    """

    cors_allow_origins: List[str] = Field(
        default=["*"],
        env="CORS_ALLOW_ORIGINS",
    )
    cors_allow_methods: List[str] = Field(
        default=["GET", "POST", "PUT", "DELETE"],
        env="CORS_ALLOW_METHODS",
    )
    cors_allow_headers: List[str] = Field(
        default=["*"],
        env="CORS_ALLOW_HEADERS",
    )
    cors_allow_credentials: bool = Field(
        default=True,
        env="CORS_ALLOW_CREDENTIALS",
    )

    class Config:
        env_file = ".env"
        case_sensitive = True


# =========================
# Фабрика приложения
# =========================

def create_app() -> FastAPI:
    """
    Создаёт и конфигурирует FastAPI-приложение.
    """
    settings = AppSettings()

    app = FastAPI(title="Configured FastAPI App")

    _configure_cors(app, settings)

    return app


# =========================
# Настройка Middleware
# =========================

def _configure_cors(app: FastAPI, settings: AppSettings) -> None:
    """
    Подключает CORS Middleware к приложению.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
        allow_credentials=settings.cors_allow_credentials,
    )


# =========================
# Точка входа
# =========================

app = create_app()
