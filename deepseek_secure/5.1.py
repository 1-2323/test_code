from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import os

def setup_cors(app: FastAPI):
    """
    Middleware для настройки CORS-политики.
    
    Разрешает запросы только с указанных доменов.
    Для production окружения использует конкретные домены из переменных окружения.
    Для development окружения можно настроить список разрешенных источников.
    """
    
    # Получаем список разрешенных доменов из переменных окружения
    allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
    
    if allowed_origins_env:
        # Разделяем домены по запятой и очищаем от пробелов
        allowed_origins: List[str] = [
            origin.strip() for origin in allowed_origins_env.split(",") 
            if origin.strip()
        ]
    else:
        # Значения по умолчанию для development
        # ЗАМЕНИТЕ эти домены на конкретные домены вашего приложения
        allowed_origins = [
            "http://localhost:3000",
            "https://example.com",
            "https://app.example.com",
        ]
    
    # Дополнительные безопасные настройки для production
    allow_credentials = os.getenv("ALLOW_CREDENTIALS", "false").lower() == "true"
    
    # Настраиваем CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,  # Конкретные домены, без wildcard
        allow_credentials=allow_credentials,  # Разрешать куки только при необходимости
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-CSRF-Token",
        ],
        expose_headers=[
            "Content-Length",
            "X-Total-Count",
            "Link",
        ],
        max_age=600,  # Кеширование preflight запросов на 10 минут
    )
    
    return app

# Пример использования в основном файле приложения:
# app = FastAPI()
# app = setup_cors(app)