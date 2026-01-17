import sys
import logging
from typing import Final, Optional
import httpx
from pydantic import BaseModel, HttpUrl, Field, ValidationError, ConfigDict

# --- Схема конфигурации ---

class AppConfig(BaseModel):
    """
    Строго типизированная модель конфигурации.
    Любое отклонение от схемы приведет к немедленной остановке.
    """
    model_config = ConfigDict(frozen=True, extra='forbid')

    api_endpoint: HttpUrl
    db_connection_string: str = Field(..., min_length=10)
    auth_secret: str = Field(..., min_length=32)
    max_retries: int = Field(default=3, ge=1, le=10)
    debug_mode: bool = False

# --- Загрузчик конфигурации ---

class ConfigLoader:
    """Сервис безопасной инициализации приложения из внешнего API."""
    
    _config: Optional[AppConfig] = None

    def __init__(self, config_url: str):
        self.config_url = config_url
        self.logger = logging.getLogger("ConfigLoader")

    async def fetch_and_initialize(self) -> AppConfig:
        """
        Загружает конфиг. В случае любой ошибки (сеть, HTTP, валидация)
        принудительно завершает процесс.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.config_url)
                
                # Проверка статуса ответа (не допускаем 4xx/5xx)
                response.raise_for_status()
                
                # Парсинг JSON
                raw_data = response.json()
                
                # Валидация данных по схеме
                self._config = AppConfig(**raw_data)
                
                self.logger.info("Configuration successfully initialized.")
                return self._config

        except (httpx.HTTPError, httpx.NetworkError) as e:
            self.logger.critical(f"NETWORK_ERROR: Unable to fetch config from {self.config_url}. Details: {e}")
            sys.exit(1)  # Остановка приложения при сбое сети

        except ValidationError as e:
            self.logger.critical(f"CONFIG_VALIDATION_ERROR: Received invalid data. Details: {e.json()}")
            sys.exit(1)  # Остановка при получении небезопасных/некорректных настроек

        except Exception as e:
            self.logger.critical(f"UNEXPECTED_INITIALIZATION_ERROR: {e}")
            sys.exit(1)

    @property
    def config(self) -> AppConfig:
        """Гарантирует доступ только к инициализированному объекту."""
        if self._config is None:
            self.logger.critical("ACCESS_ERROR: Attempted to access config before initialization.")
            sys.exit(1)
        return self._config