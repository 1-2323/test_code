import yaml
import logging
from typing import List, Dict, Any, Final, Optional
from pydantic import BaseModel, Field, ValidationError, ConfigDict


# --- Схемы валидации плагинов ---

class PluginModel(BaseModel):
    """Схема конфигурации отдельного плагина."""
    model_config = ConfigDict(extra='forbid')  # Запрещаем лишние поля

    name: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    enabled: bool = True
    priority: int = Field(default=10, ge=1, le=100)
    settings: Dict[str, Any] = Field(default_factory=dict)


class AppConfigModel(BaseModel):
    """Схема корневого файла конфигурации."""
    model_config = ConfigDict(extra='forbid')

    app_version: str
    plugins: List[PluginModel]


# --- Сервис загрузки конфигураций ---

class PluginConfigLoader:
    """
    Загрузчик конфигураций плагинов с защитой от десериализации кода (YAML Injection).
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._logger = logging.getLogger("PluginLoader")

    def load_config(self) -> Optional[AppConfigModel]:
        """
        Читает YAML, валидирует структуру и возвращает объект конфигурации.
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                # 1. Используем safe_load вместо load
                # Это блокирует использование тегов !!python/object
                raw_data = yaml.safe_load(f)

            if raw_data is None:
                raise ValueError("Configuration file is empty")

            # 2. Строгая проверка типов и структуры через Pydantic
            config = AppConfigModel(**raw_data)
            self._logger.info(f"Successfully loaded {len(config.plugins)} plugins.")
            return config

        except FileNotFoundError:
            self._logger.error(f"Config file not found: {self.config_path}")
        except yaml.YAMLError as e:
            self._logger.error(f"YAML parsing error: {str(e)}")
        except ValidationError as e:
            self._logger.error(f"Configuration validation failed: {e.json()}")
        except Exception as e:
            self._logger.error(f"Unexpected error: {str(e)}")

        return None


# --- Пример использования ---

# YAML содержимое:
# app_version: "2.1.0"
# plugins:
#   - name: "auth_provider"
#     version: "1.0.2"
#     enabled: true
#     priority: 1
#     settings:
#       timeout: 30