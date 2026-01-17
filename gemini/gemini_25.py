import os
from enum import Enum
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class AppMode(str, Enum):
    """Доступные режимы работы приложения."""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"

class AppConfig(BaseSettings):
    """
    Глобальный менеджер конфигураций.
    Автоматически считывает переменные из окружения или .env файла.
    """
    
    # 1. Основные параметры режима
    MODE: AppMode = Field(default=AppMode.DEVELOPMENT, alias="APP_MODE")
    
    # 2. Параметры сервера
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    RELOAD: bool = True
    
    # 3. Логирование и отладка
    LOG_LEVEL: str = "DEBUG"
    SHOW_DEBUG_INFO: bool = True
    
    # Конфигурация Pydantic для работы с .env
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @classmethod
    def load(cls):
        """
        Фабричный метод, адаптирующий настройки под APP_MODE.
        Переопределяет параметры в зависимости от среды исполнения.
        """
        # Сначала загружаем базовые настройки (из .env или ENV)
        temp_config = cls()
        
        if temp_config.MODE == AppMode.PRODUCTION:
            return cls(
                LOG_LEVEL="ERROR",
                SHOW_DEBUG_INFO=False,
                RELOAD=False
            )
        
        elif temp_config.MODE == AppMode.TESTING:
            return cls(
                LOG_LEVEL="CRITICAL",
                SHOW_DEBUG_INFO=True,
                PORT=8001
            )
            
        return temp_config

def initialize_logging(config: AppConfig):
    """Инициализирует систему логирования на основе конфига."""
    import logging
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logging.info(f"Система запущена в режиме: {config.MODE.value}")

# --- Пример использования ---

if __name__ == "__main__":
    # Симуляция переменной окружения (обычно задается в терминале или Docker)
    os.environ["APP_MODE"] = "production"
    os.environ["PORT"] = "443"

    # Загрузка и применение конфигурации
    config = AppConfig.load()
    initialize_logging(config)

    print("-" * 30)
    print(f"Server Host: {config.HOST}")
    print(f"Server Port: {config.PORT}")
    print(f"Debug Mode Active: {config.SHOW_DEBUG_INFO}")
    print(f"Hot Reload: {config.RELOAD}")
    print("-" * 30)