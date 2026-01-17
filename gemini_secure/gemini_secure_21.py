import os
from typing import List, Final
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


class AppSettings(BaseSettings):
    """
    Валидатор конфигурации приложения. 
    Автоматически считывает переменные из .env и проверяет их типы.
    """
    # Строгая валидация списка разрешенных доменов
    CORS_ORIGINS: List[AnyHttpUrl] = []

    # Разрешенные методы и заголовки (лучше держать их конкретными)
    CORS_METHODS: List[str] = ["GET", "POST", "PUT", "DELETE"]
    CORS_HEADERS: List[str] = ["Content-Type", "Authorization", "X-Requested-With"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Преобразует строку из .env (через запятую) в список URL."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        return v

    # Подгрузка из файла .env
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )


def create_app() -> FastAPI:
    """
    Фабрика инициализации приложения с настроенным Middleware.
    """
    # 1. Загрузка и валидация настроек
    settings = AppSettings()

    app = FastAPI(
        title="Secure FastAPI App",
        version="1.0.0"
    )

    # 2. Настройка CORS
    # Мы явно передаем конкретные списки вместо "*"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=settings.CORS_METHODS,
        allow_headers=settings.CORS_HEADERS,
        expose_headers=["Content-Disposition"], # Например, для скачивания файлов
        max_age=3600, # Кэширование preflight-запроса на 1 час
    )

    @app.get("/health")
    async def health_check():
        return {"status": "secure", "cors_configured": True}

    return app

# Пример содержимого файла .env:
# CORS_ORIGINS=https://frontend.example.com,https://admin.example.com

app = create_app()