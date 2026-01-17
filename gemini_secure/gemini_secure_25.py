import os
import logging
from enum import Enum
from typing import Optional, Final
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class AppMode(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"

class AppConfig(BaseSettings):
    """
    Менеджер конфигураций приложения.
    Автоматически синхронизируется с переменными окружения.
    """
    
    # Режим работы приложения
    MODE: AppMode = Field(default=AppMode.DEVELOPMENT)
    
    # Секретные ключи хранятся как SecretStr (не отображаются при печати/в логах)
    SECRET_KEY: SecretStr
    DATABASE_URL: SecretStr
    
    # Параметры отладки
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # Параметры сервера
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Защита: Принудительное отключение отладки в режиме Production
    @field_validator("DEBUG", mode="after")
    @classmethod
    def check_debug_in_production(cls, v: bool, info) -> bool:
        if info.data.get("MODE") == AppMode.PRODUCTION and v is True:
            # Блокируем запуск, если в проде включен дебаг
            raise ValueError("DEBUG mode must be FALSE in PRODUCTION environment!")
        return v

    @field_validator("LOG_LEVEL", mode="after")
    @classmethod
    def set_proper_log_level(cls, v: str, info) -> str:
        if info.data.get("MODE") == AppMode.PRODUCTION:
            return "WARNING" # В проде пишем только важное
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore" # Игнорируем лишние переменные окружения
    )

class ConfigManager:
    """
    Инициализатор окружения на основе выбранного режима.
    """
    
    def __init__(self):
        self.settings = AppConfig()
        self._setup_logging()

    def _setup_logging(self):
        """Настройка логирования в зависимости от уровня."""
        logging.basicConfig(
            level=self.settings.LOG_LEVEL,
            format="%(asctime)s - [%(levelname)s] - %(name)s: %(message)s"
        )
        logger = logging.getLogger("AppInit")
        logger.info(f"Application started in {self.settings.MODE} mode")

    def get_server_params(self) -> dict:
        """Возвращает параметры для запуска сервера (например, для uvicorn)."""
        return {
            "host": self.settings.HOST,
            "port": self.settings.PORT,
            "reload": self.settings.DEBUG  # Автоперезагрузка только в дебаге
        }

# --- Пример .env файла ---
# MODE=production
# SECRET_KEY=very-secret-string-123
# DATABASE_URL=postgresql://user:pass@localhost/db
# DEBUG=false