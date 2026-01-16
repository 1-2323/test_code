import requests
import sys
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """Конфигурация приложения"""
    api_key: str
    database_url: str
    max_connections: int
    debug_mode: bool
    allowed_hosts: list[str]
    

class ConfigLoadError(Exception):
    """Исключение при ошибке загрузки конфигурации"""
    pass


class SecureConfigLoader:
    """
    Безопасный загрузчик конфигурации из внешнего API.
    При сбое завершает работу приложения.
    """
    
    def __init__(self, config_api_url: str, api_token: str, timeout: int = 10):
        """
        Инициализация загрузчика конфигурации
        
        Args:
            config_api_url: URL API конфигурации
            api_token: токен для доступа к API
            timeout: таймаут запроса в секундах
        """
        self.config_api_url = config_api_url
        self.api_token = api_token
        self.timeout = timeout
        
    def load_configuration(self) -> AppConfig:
        """
        Загрузка конфигурации из внешнего API
        
        Returns:
            Загруженная конфигурация приложения
            
        Raises:
            ConfigLoadError: если не удалось загрузить конфигурацию
            SystemExit: если конфигурация критически важна и загрузить не удалось
        """
        try:
            logger.info(f"Загрузка конфигурации из {self.config_api_url}")
            
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                self.config_api_url,
                headers=headers,
                timeout=self.timeout
            )
            
            # Проверяем статус ответа
            response.raise_for_status()
            
            # Парсим JSON
            config_data = response.json()
            
            # Валидируем обязательные поля
            self._validate_config(config_data)
            
            # Создаем объект конфигурации
            config = AppConfig(
                api_key=config_data["api_key"],
                database_url=config_data["database_url"],
                max_connections=config_data["max_connections"],
                debug_mode=config_data.get("debug_mode", False),
                allowed_hosts=config_data.get("allowed_hosts", [])
            )
            
            logger.info("Конфигурация успешно загружена")
            return config
            
        except requests.exceptions.Timeout as e:
            error_msg = f"Таймаут при загрузке конфигурации: {e}"
            logger.error(error_msg)
            self._fail_gracefully(error_msg)
            
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Ошибка соединения при загрузке конфигурации: {e}"
            logger.error(error_msg)
            self._fail_gracefully(error_msg)
            
        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP ошибка при загрузке конфигурации: {e}"
            logger.error(error_msg)
            self._fail_gracefully(error_msg)
            
        except json.JSONDecodeError as e:
            error_msg = f"Ошибка парсинга JSON конфигурации: {e}"
            logger.error(error_msg)
            self._fail_gracefully(error_msg)
            
        except KeyError as e:
            error_msg = f"Отсутствует обязательное поле в конфигурации: {e}"
            logger.error(error_msg)
            self._fail_gracefully(error_msg)
            
        except Exception as e:
            error_msg = f"Неизвестная ошибка при загрузке конфигурации: {e}"
            logger.error(error_msg)
            self._fail_gracefully(error_msg)
            
        # Эта точка недостижима, но нужна для статического анализатора типов
        raise ConfigLoadError("Не удалось загрузить конфигурацию")
    
    def _validate_config(self, config_data: Dict[str, Any]) -> None:
        """
        Валидация загруженной конфигурации
        
        Args:
            config_data: данные конфигурации
            
        Raises:
            ValueError: если конфигурация невалидна
        """
        required_fields = ["api_key", "database_url", "max_connections"]
        
        for field in required_fields:
            if field not in config_data:
                raise KeyError(f"Отсутствует обязательное поле: {field}")
            
        # Проверка безопасности
        if config_data.get("debug_mode", False):
            logger.warning("Включен режим отладки в production конфигурации")
            
        if not config_data.get("allowed_hosts"):
            logger.warning("Список разрешенных хостов пуст")
    
    def _fail_gracefully(self, error_message: str) -> None:
        """
        Грациозное завершение работы при ошибке загрузки конфигурации
        
        Args:
            error_message: сообщение об ошибке
            
        Raises:
            SystemExit: всегда вызывает завершение работы
        """
        logger.critical(f"Критическая ошибка: {error_message}")
        logger.critical("Приложение не может быть запущено с небезопасными настройками по умолчанию")
        
        # Выводим сообщение в stderr
        print(f"ОШИБКА: {error_message}", file=sys.stderr)
        print("Приложение завершено из-за ошибки конфигурации", file=sys.stderr)
        
        # Завершаем работу с ненулевым кодом
        sys.exit(1)


# Пример использования
def main():
    """Основная функция приложения"""
    try:
        # Инициализация загрузчика конфигурации
        config_loader = SecureConfigLoader(
            config_api_url="https://config-api.example.com/v1/config",
            api_token="your-secret-token",
            timeout=15
        )
        
        # Загрузка конфигурации (при ошибке приложение завершится)
        config = config_loader.load_configuration()
        
        # Если дошли сюда - конфигурация загружена успешно
        logger.info(f"Конфигурация загружена: {config}")
        
        # Запуск основного приложения
        run_application(config)
        
    except ConfigLoadError as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")
        sys.exit(1)


def run_application(config: AppConfig) -> None:
    """Запуск приложения с загруженной конфигурацией"""
    print(f"Приложение запущено с конфигурацией:")
    print(f"  API Key: {'*' * len(config.api_key)}")
    print(f"  Database: {config.database_url}")
    print(f"  Max connections: {config.max_connections}")
    print(f"  Debug mode: {config.debug_mode}")


if __name__ == "__main__":
    main()