import os
from typing import List
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Загрузка переменных окружения из .env файла
load_dotenv()

class AppConfig:
    """Класс для централизованного управления конфигурациями приложения."""
    
    # Чтение настроек CORS из окружения с дефолтными значениями для разработки
    # Пример в .env: ALLOWED_ORIGINS=https://frontend.com,https://admin.com
    CORS_ORIGINS: List[str] = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    
    # Разрешенные HTTP методы
    CORS_METHODS: List[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
    
    # Разрешенные заголовки (включая авторизацию)
    CORS_HEADERS: List[str] = ["Content-Type", "Authorization", "X-Requested-With", "Accept"]
    
    APP_TITLE: str = "FastAPI Production Service"
    APP_VERSION: str = "1.0.0"
    DEBUG_MODE: bool = os.getenv("DEBUG", "False").lower() == "true"

def create_app() -> FastAPI:
    """
    Фабрика инициализации FastAPI приложения.
    
    Логика работы:
    1. Инициализация базового экземпляра FastAPI.
    2. Настройка CORS Middleware (безопасность кросс-доменных запросов).
    3. Определение базовых эндпоинтов мониторинга.
    """
    config = AppConfig()
    
    app = FastAPI(
        title=config.APP_TITLE,
        version=config.APP_VERSION,
        debug=config.DEBUG_MODE
    )

    # Настройка Middleware для CORS
    # Позволяет фронтенд-приложениям с других доменов безопасно обращаться к API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=config.CORS_METHODS,
        allow_headers=config.CORS_HEADERS,
    )

    @app.get("/health", tags=["Monitoring"])
    async def health_check():
        """Эндпоинт для проверки жизнеспособности сервиса."""
        return {
            "status": "healthy",
            "version": config.APP_VERSION,
            "cors_active": True,
            "allowed_origins": config.CORS_ORIGINS
        }

    return app

# Создание экземпляра для запуска через uvicorn (uvicorn main:app --reload)
app = create_app()

if __name__ == "__main__":
    # Демонстрация загруженных настроек
    print(f"--- Инициализация {app.title} ---")
    print(f"Режим отладки: {AppConfig.DEBUG_MODE}")
    print(f"Разрешенные источники (CORS): {AppConfig.CORS_ORIGINS}")