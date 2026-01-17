import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# =========================
# Режимы приложения
# =========================

class AppMode(str, Enum):
    """
    Поддерживаемые режимы запуска приложения.
    """

    DEVELOPMENT = "development"
    PRODUCTION = "production"


# =========================
# Конфигурация логирования
# =========================

@dataclass(frozen=True)
class LoggingConfig:
    """
    Конфигурация логирования приложения.
    """

    level: int
    format: str
    enable_debug_logs: bool


# =========================
# Конфигурация сервера
# =========================

@dataclass(frozen=True)
class ServerConfig:
    """
    Конфигурация запуска сервера.
    """

    host: str
    port: int
    reload: bool
    workers: int


# =========================
# Основной менеджер конфигурации
# =========================

class AppConfig:
    """
    Менеджер конфигураций приложения.

    Отвечает за:
    - выбор режима (dev / prod)
    - настройку логирования
    - параметры запуска сервера
    """

    def __init__(self, mode: Optional[str] = None) -> None:
        self._mode: AppMode = self._resolve_mode(mode)
        self.logging: LoggingConfig = self._build_logging_config()
        self.server: ServerConfig = self._build_server_config()

        self._configure_logging()

    # =========================
    # Public API
    # =========================

    @property
    def is_development(self) -> bool:
        return self._mode == AppMode.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self._mode == AppMode.PRODUCTION

    @property
    def mode(self) -> AppMode:
        return self._mode

    # =========================
    # Внутренняя логика
    # =========================

    def _resolve_mode(self, explicit_mode: Optional[str]) -> AppMode:
        """
        Определяет режим запуска приложения.
        """
        mode_value = (
            explicit_mode
            or os.getenv("APP_MODE", AppMode.DEVELOPMENT.value)
        ).lower()

        try:
            return AppMode(mode_value)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported APP_MODE: {mode_value}"
            ) from exc

    def _build_logging_config(self) -> LoggingConfig:
        """
        Формирует конфигурацию логирования.
        """
        if self.is_development:
            return LoggingConfig(
                level=logging.DEBUG,
                format="[DEV] %(asctime)s | %(levelname)s | %(message)s",
                enable_debug_logs=True,
            )

        return LoggingConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            enable_debug_logs=False,
        )

    def _build_server_config(self) -> ServerConfig:
        """
        Формирует конфигурацию сервера.
        """
        if self.is_development:
            return ServerConfig(
                host="127.0.0.1",
                port=8000,
                reload=True,
                workers=1,
            )

        return ServerConfig(
            host="0.0.0.0",
            port=8000,
            reload=False,
            workers=max(2, os.cpu_count() or 2),
        )

    def _configure_logging(self) -> None:
        """
        Применяет конфигурацию логирования.
        """
        logging.basicConfig(
            level=self.logging.level,
            format=self.logging.format,
        )

        if not self.logging.enable_debug_logs:
            logging.getLogger("uvicorn.access").disabled = True
            logging.getLogger("uvicorn.error").setLevel(logging.INFO)


# =========================
# Пример использования
# =========================

def load_app_config() -> AppConfig:
    """
    Загружает конфигурацию приложения.
    """
    return AppConfig()


if __name__ == "__main__":
    config = load_app_config()

    logging.info("Application started")
    logging.info("Mode: %s", config.mode.value)
    logging.info(
        "Server: %s:%s | reload=%s | workers=%s",
        config.server.host,
        config.server.port,
        config.server.reload,
        config.server.workers,
    )
