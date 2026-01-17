import os
import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv


# =========================
# ENV LOADING
# =========================

load_dotenv()


# =========================
# ENV ENUM
# =========================

class AppMode(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


# =========================
# CONFIG SCHEMA
# =========================

class AppConfig(BaseModel):
    """
    Глобальная конфигурация приложения.
    """

    mode: AppMode
    debug: bool
    log_level: int
    host: str
    port: int
    secret_key: str = Field(min_length=32)

    class Config:
        extra = "forbid"


# =========================
# CONFIG MANAGER
# =========================

class AppConfigManager:
    """
    Менеджер конфигураций приложения.
    Управляет режимами Development / Production.
    """

    def __init__(self) -> None:
        self._config: Optional[AppConfig] = None

    def load(self) -> AppConfig:
        """
        Загружает и валидирует конфигурацию из окружения.
        """
        try:
            mode = AppMode(os.getenv("APP_MODE", "development").lower())

            if mode == AppMode.DEVELOPMENT:
                config = AppConfig(
                    mode=mode,
                    debug=True,
                    log_level=logging.DEBUG,
                    host=os.getenv("APP_HOST", "127.0.0.1"),
                    port=int(os.getenv("APP_PORT", "8000")),
                    secret_key=self._load_secret(),
                )
            else:
                config = AppConfig(
                    mode=mode,
                    debug=False,
                    log_level=logging.INFO,
                    host=os.getenv("APP_HOST", "0.0.0.0"),
                    port=int(os.getenv("APP_PORT", "8000")),
                    secret_key=self._load_secret(),
                )

        except (ValidationError, ValueError) as exc:
            raise RuntimeError("Некорректная конфигурация приложения") from exc

        self._config = config
        self._configure_logging(config)
        return config

    def get(self) -> AppConfig:
        """
        Возвращает загруженную конфигурацию.
        """
        if not self._config:
            raise RuntimeError("Конфигурация не загружена")
        return self._config

    def _load_secret(self) -> str:
        """
        Загружает секретный ключ из окружения.
        """
        secret = os.getenv("APP_SECRET_KEY")
        if not secret:
            raise RuntimeError("Секретный ключ не задан")
        return secret

    def _configure_logging(self, config: AppConfig) -> None:
        """
        Настраивает глобальный уровень логирования.
        """
        logging.basicConfig(
            level=config.log_level,
            format="%(asctime)s | %(levelname)s | %(message)s",
        )


# =========================
# INITIALIZATION
# =========================

config_manager = AppConfigManager()
app_config = config_manager.load()
