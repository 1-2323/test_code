import os
from fastapi import FastAPI
from pydantic import BaseSettings
from typing import List, Optional

class CorsSettings(BaseSettings):
    """Настройки CORS из переменных окружения"""
    cors_allow_origins: str = "*"
    cors_allow_credentials: bool = True
    cors_allow_methods: str = "*"
    cors_allow_headers: str = "*"
    cors_expose_headers: str = ""
    cors_max_age: int = 600
    
    class Config:
        env_file = ".env"

def setup_cors_dynamic(app: FastAPI):
    """Настройка CORS с динамической конфигурацией из переменных окружения"""
    
    settings = CorsSettings()
    
    # Парсим строки в списки
    allow_origins = settings.cors_allow_origins.split(",") if settings.cors_allow_origins else ["*"]
    allow_methods = settings.cors_allow_methods.split(",") if settings.cors_allow_methods else ["*"]
    allow_headers = settings.cors_allow_headers.split(",") if settings.cors_allow_headers else ["*"]
    expose_headers = settings.cors_expose_headers.split(",") if settings.cors_expose_headers else []
    
    # Настраиваем middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
        expose_headers=expose_headers,
        max_age=settings.cors_max_age
    )