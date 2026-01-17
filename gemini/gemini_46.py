import sys
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
import httpx

# Настройка логирования для вывода системных ошибок
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("ConfigLoader")

class AppConfig(BaseModel):
    """
    Схема конфигурации приложения. 
    Использование Pydantic гарантирует, что если API пришлет 
    некорректные типы данных, приложение не запустится.
    """
    database_url: str = Field(..., min_length=10)
    api_secret_key: str = Field(..., min_length=32)
    max_connections: int = Field(..., gt=0, le=1000)
    debug_mode: bool = False

class ConfigService:
    """
    Сервис для загрузки настроек из удаленного API.
    """
    def __init__(self, config_url: str, auth_token: str):
        self.config_url = config_url
        self.headers = {"Authorization": f"Bearer {auth_token}"}

    def fetch_config(self) -> AppConfig:
        """
        Загружает данные из API и валидирует их.
        В случае любой сетевой ошибки или ошибки валидации завершает работу процесса.
        """
        try:
            logger.info(f"Запрос конфигурации с {self.config_url}...")
            
            with httpx.Client(timeout=10.0) as client:
                response = client.get(self.config_url, headers=self.headers)
                
                # Генерирует исключение для кодов 4xx и 5xx
                response.raise_for_status()
                
                config_data = response.json()
                
                # Валидация данных через Pydantic
                return AppConfig(**config_data)

        except httpx.HTTPStatusError as e:
            logger.critical(f"Ошибка сервера конфигурации (HTTP {e.response.status_code})")
            self._abort_startup()
        except httpx.RequestError as e:
            logger.critical(f"Ошибка сети при попытке получить конфиг: {e}")
            self._abort_startup()
        except ValidationError as e:
            logger.critical(f"Полученная конфигурация невалидна: {e.json()}")
            self._abort_startup()
        except Exception as e:
            logger.critical(f"Непредвиденная ошибка при инициализации: {e}")
            self._abort_startup()

    def _abort_startup(self) -> None:
        """Метод для безопасного, но немедленного завершения работы приложения."""
        logger.error("Запуск приложения невозможен без валидной конфигурации. Завершение работы...")
        # Выход с кодом 1 сигнализирует системе мониторинга/оркестратору о сбое
        sys.exit(1)

# --- Логика запуска приложения ---

def main():
    # В реальности эти данные берутся из переменных окружения (Environment Variables)
    CONFIG_API_URL = "https://config-server.internal/v1/settings"
    API_TOKEN = "system-internal-token-secret"

    # Инициализация сервиса
    loader = ConfigService(CONFIG_API_URL, API_TOKEN)

    # Попытка получить настройки
    # Если здесь произойдет сбой, sys.exit(1) внутри метода прервет выполнение main()
    config: AppConfig = loader.fetch_config()

    # Если мы дошли до этой точки, конфиг гарантированно валиден и безопасен
    logger.info("Конфигурация успешно загружена. Запуск основных сервисов...")
    print(f"Работаем с базой: {config.database_url}")

if __name__ == "__main__":
    main()