# app/config/config_manager.py
import os
import json
import logging
from typing import Any, Dict, Optional
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseSettings, Field, validator


class Environment(str, Enum):
    """Перечисление поддерживаемых окружений"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Уровни логирования"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AppConfig(BaseSettings):
    """
    Главный класс конфигурации приложения
    Использует pydantic для валидации и парсинга
    """
    
    # Базовые настройки
    ENVIRONMENT: Environment = Field(default=Environment.DEVELOPMENT, env="ENVIRONMENT")
    APP_NAME: str = Field(default="My FastAPI App", env="APP_NAME")
    APP_VERSION: str = Field(default="1.0.0", env="APP_VERSION")
    DEBUG: bool = Field(default=False, env="DEBUG")
    
    # Настройки сервера
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=8000, env="PORT")
    WORKERS: int = Field(default=1, env="WORKERS")
    RELOAD: bool = Field(default=True, env="RELOAD")
    
    # Настройки базы данных
    DATABASE_URL: str = Field(default="sqlite:///./app.db", env="DATABASE_URL")
    DATABASE_POOL_SIZE: int = Field(default=5, env="DATABASE_POOL_SIZE")
    DATABASE_MAX_OVERFLOW: int = Field(default=10, env="DATABASE_MAX_OVERFLOW")
    
    # Настройки безопасности
    SECRET_KEY: str = Field(default="your-secret-key-change-in-production", env="SECRET_KEY")
    ALGORITHM: str = Field(default="HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # Настройки логирования
    LOG_LEVEL: LogLevel = Field(default=LogLevel.INFO, env="LOG_LEVEL")
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        env="LOG_FORMAT"
    )
    LOG_FILE: Optional[str] = Field(default=None, env="LOG_FILE")
    
    # Дополнительные настройки
    API_PREFIX: str = Field(default="/api", env="API_PREFIX")
    CORS_ORIGINS: str = Field(default="http://localhost:3000", env="CORS_ORIGINS")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    @validator("DEBUG", pre=True, always=True)
    def set_debug_based_on_environment(cls, v, values):
        """Автоматически устанавливает DEBUG на основе окружения"""
        if "ENVIRONMENT" in values:
            return values["ENVIRONMENT"] == Environment.DEVELOPMENT
        return v
    
    @validator("RELOAD", pre=True, always=True)
    def set_reload_based_on_environment(cls, v, values):
        """Автоматически устанавливает RELOAD на основе окружения"""
        if "ENVIRONMENT" in values:
            return values["ENVIRONMENT"] == Environment.DEVELOPMENT
        return v
    
    @validator("WORKERS", pre=True, always=True)
    def set_workers_based_on_environment(cls, v, values):
        """Автоматически устанавливает WORKERS на основе окружения"""
        if "ENVIRONMENT" in values:
            if values["ENVIRONMENT"] == Environment.PRODUCTION:
                import multiprocessing
                return multiprocessing.cpu_count() * 2 + 1
        return v or 1
    
    @validator("LOG_LEVEL", pre=True, always=True)
    def set_log_level_based_on_environment(cls, v, values):
        """Автоматически устанавливает уровень логирования на основе окружения"""
        if "ENVIRONMENT" in values:
            if values["ENVIRONMENT"] == Environment.DEVELOPMENT:
                return LogLevel.DEBUG
            elif values["ENVIRONMENT"] == Environment.PRODUCTION:
                return LogLevel.WARNING
        return v or LogLevel.INFO


class ConfigManager:
    """
    Менеджер конфигураций приложения
    Обеспечивает загрузку, валидацию и предоставление настроек
    """
    
    _instance: Optional['ConfigManager'] = None
    _config: Optional[AppConfig] = None
    
    def __new__(cls):
        """Реализация singleton паттерна"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Инициализация менеджера конфигураций"""
        if self._config is None:
            self.load_config()
    
    def load_config(self, env_file: str = ".env") -> None:
        """
        Загрузка конфигурации из файла .env
        
        Args:
            env_file: Путь к файлу .env
        """
        # Загрузка переменных окружения
        load_dotenv(env_file)
        
        # Создание конфигурации с валидацией
        self._config = AppConfig()
        
        # Дополнительная загрузка из конфигурационных файлов
        self._load_config_files()
    
    def _load_config_files(self) -> None:
        """Загрузка дополнительных конфигурационных файлов"""
        config_dir = Path("config")
        
        if config_dir.exists():
            # Загрузка общего конфига
            common_config = config_dir / "common.json"
            if common_config.exists():
                self._update_from_file(common_config)
            
            # Загрузка конфига окружения
            env_config = config_dir / f"{self._config.ENVIRONMENT.value}.json"
            if env_config.exists():
                self._update_from_file(env_config)
    
    def _update_from_file(self, file_path: Path) -> None:
        """
        Обновление конфигурации из JSON файла
        
        Args:
            file_path: Путь к JSON файлу
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Обновление конфигурации
            for key, value in config_data.items():
                if hasattr(self._config, key.upper()):
                    setattr(self._config, key.upper(), value)
                    
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config file {file_path}: {e}")
    
    def get_config(self) -> AppConfig:
        """
        Получение текущей конфигурации
        
        Returns:
            Объект конфигурации AppConfig
        """
        if self._config is None:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        return self._config
    
    def get_logging_config(self) -> Dict[str, Any]:
        """
        Генерация конфигурации для logging модуля
        
        Returns:
            Словарь с настройками логирования
        """
        config = self.get_config()
        
        log_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": config.LOG_FORMAT,
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "format": "%(asctime)s %(name)s %(levelname)s %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": config.LOG_LEVEL.value,
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                }
            },
            "loggers": {
                "": {  # Root logger
                    "handlers": ["console"],
                    "level": config.LOG_LEVEL.value,
                    "propagate": False
                },
                "app": {
                    "handlers": ["console"],
                    "level": config.LOG_LEVEL.value,
                    "propagate": False
                },
                "uvicorn": {
                    "handlers": ["console"],
                    "level": "INFO",
                    "propagate": False
                }
            }
        }
        
        # Добавление файлового обработчика, если указан файл лога
        if config.LOG_FILE:
            log_config["handlers"]["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "level": config.LOG_LEVEL.value,
                "formatter": "default" if config.ENVIRONMENT != Environment.PRODUCTION else "json",
                "filename": config.LOG_FILE,
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
            }
            log_config["loggers"][""]["handlers"].append("file")
            log_config["loggers"]["app"]["handlers"].append("file")
        
        return log_config
    
    def setup_logging(self) -> None:
        """Настройка системы логирования на основе конфигурации"""
        import logging.config
        
        log_config = self.get_logging_config()
        logging.config.dictConfig(log_config)
    
    def get_server_config(self) -> Dict[str, Any]:
        """
        Получение конфигурации сервера для запуска
        
        Returns:
            Словарь с параметрами сервера
        """
        config = self.get_config()
        
        server_config = {
            "host": config.HOST,
            "port": config.PORT,
            "reload": config.RELOAD,
            "workers": config.WORKERS,
            "log_level": config.LOG_LEVEL.value.lower(),
        }
        
        # Дополнительные настройки для production
        if config.ENVIRONMENT == Environment.PRODUCTION:
            server_config.update({
                "access_log": True,
                "proxy_headers": True,
                "forwarded_allow_ips": "*",
                "timeout_keep_alive": 5,
            })
        
        return server_config
    
    def print_config_summary(self) -> None:
        """Вывод сводки конфигурации в консоль"""
        config = self.get_config()
        
        print("=" * 50)
        print("APPLICATION CONFIGURATION SUMMARY")
        print("=" * 50)
        print(f"Environment: {config.ENVIRONMENT.value}")
        print(f"Debug Mode: {config.DEBUG}")
        print(f"App Name: {config.APP_NAME}")
        print(f"App Version: {config.APP_VERSION}")
        print(f"Log Level: {config.LOG_LEVEL.value}")
        print(f"Database URL: {config.DATABASE_URL[:50]}...")
        print(f"Server: {config.HOST}:{config.PORT}")
        print(f"Workers: {config.WORKERS}")
        print(f"Auto Reload: {config.RELOAD}")
        print("=" * 50)


# Глобальный экземпляр менеджера конфигураций
config_manager = ConfigManager()


def get_config() -> AppConfig:
    """
    Функция для быстрого доступа к конфигурации
    
    Returns:
        Объект конфигурации AppConfig
    """
    return config_manager.get_config()


# Пример использования
if __name__ == "__main__":
    # Загрузка конфигурации
    config_manager.load_config()
    
    # Вывод сводки
    config_manager.print_config_summary()
    
    # Настройка логирования
    config_manager.setup_logging()
    
    # Получение конфигурации сервера
    server_config = config_manager.get_server_config()
    print(f"\nServer config: {server_config}")