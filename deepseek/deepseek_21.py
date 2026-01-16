# app/main.py
import os
from typing import List
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Загрузка переменных окружения
load_dotenv()

def create_app() -> FastAPI:
    """
    Фабрика для создания FastAPI приложения с настройками CORS
    """
    app = FastAPI(
        title="API Service",
        description="Основное приложение API",
        version="1.0.0"
    )
    
    # Чтение настроек CORS из .env файла
    allowed_origins = _parse_origins(os.getenv("ALLOWED_ORIGINS", ""))
    allowed_methods = _parse_list(os.getenv("ALLOWED_METHODS", "GET,POST,PUT,DELETE,OPTIONS"))
    allowed_headers = _parse_list(os.getenv("ALLOWED_HEADERS", "*"))
    allow_credentials = os.getenv("ALLOW_CREDENTIALS", "true").lower() == "true"
    
    # Настройка CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=allowed_methods,
        allow_headers=allowed_headers,
    )
    
    return app


def _parse_origins(origins_str: str) -> List[str]:
    """
    Парсит строку origins в список, поддерживая специальные значения
    """
    if not origins_str:
        return ["http://localhost:3000"]  # Значение по умолчанию
    
    if origins_str.strip() == "*":
        return ["*"]
    
    return [origin.strip() for origin in origins_str.split(",") if origin.strip()]


def _parse_list(list_str: str) -> List[str]:
    """
    Парсит строку с элементами, разделенными запятыми, в список
    """
    if list_str == "*":
        return ["*"]
    
    return [item.strip() for item in list_str.split(",") if item.strip()]


# Создание экземпляра приложения
app = create_app()


@app.get("/health")
async def health_check() -> dict:
    """Эндпоинт для проверки работоспособности"""
    return {"status": "healthy", "service": "main-api"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )