import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union


@dataclass
class Config:
    """Основной класс конфигурации приложения."""
    host: str = "localhost"
    port: int = 8080
    debug: bool = False
    database_url: str = "sqlite:///./app.db"
    log_level: str = "INFO"
    max_workers: int = 4
    timeout: float = 30.0


class ConfigLoader:
    """Загрузчик конфигурации из JSON файла с fallback-значениями."""
    
    def __init__(self, config_path: Union[str, Path] = "config.json"):
        """
        Инициализация загрузчика конфигурации.
        
        Args:
            config_path: Путь к JSON файлу конфигурации
        """
        self.config_path = Path(config_path)
        self._config_data: Dict[str, Any] = {}
        
    def load(self) -> Config:
        """
        Загружает конфигурацию из файла с fallback-значениями.
        
        Returns:
            Config: Объект конфигурации
            
        Raises:
            SystemExit: При критических ошибках конфигурации
        """
        # Загружаем данные из JSON файла если он существует
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config_data = json.load(f)
                print(f"Конфигурация загружена из {self.config_path}")
            except json.JSONDecodeError as e:
                self._critical_error(f"Ошибка синтаксиса JSON в файле конфигурации: {e}")
            except (IOError, OSError) as e:
                self._critical_error(f"Ошибка чтения файла конфигурации: {e}")
        else:
            print(f"Файл конфигурации {self.config_path} не найден. Используются значения по умолчанию.")
        
        # Создаем объект конфигурации с fallback-значениями
        try:
            config = Config(
                host=self._get_value("host", Config.host),
                port=self._get_value("port", Config.port),
                debug=self._get_value("debug", Config.debug),
                database_url=self._get_value("database_url", Config.database_url),
                log_level=self._get_value("log_level", Config.log_level),
                max_workers=self._get_value("max_workers", Config.max_workers),
                timeout=self._get_value("timeout", Config.timeout),
            )
            
            # Валидация критических параметров
            self._validate_config(config)
            
            return config
            
        except (ValueError, TypeError) as e:
            self._critical_error(f"Ошибка в данных конфигурации: {e}")
    
    def _get_value(self, key: str, default: Any) -> Any:
        """
        Получает значение из загруженных данных или использует значение по умолчанию.
        
        Args:
            key: Ключ параметра
            default: Значение по умолчанию
            
        Returns:
            Значение параметра
        """
        value = self._config_data.get(key, default)
        
        # Тип-безопасное преобразование для логических значений
        if isinstance(default, bool) and not isinstance(value, bool):
            if isinstance(value, str):
                return value.lower() in ('true', '1', 'yes', 'y')
            return bool(value)
        
        return value
    
    def _validate_config(self, config: Config) -> None:
        """
        Проверяет корректность критических параметров конфигурации.
        
        Args:
            config: Объект конфигурации
            
        Raises:
            SystemExit: При критических ошибках валидации
        """
        errors = []
        
        # Проверка порта
        if not (1 <= config.port <= 65535):
            errors.append(f"Порт должен быть в диапазоне 1-65535, получено: {config.port}")
        
        # Проверка уровня логирования
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if config.log_level.upper() not in valid_log_levels:
            errors.append(f"Недопустимый уровень логирования: {config.log_level}. "
                         f"Допустимые значения: {', '.join(valid_log_levels)}")
        
        # Проверка количества workers
        if config.max_workers < 1:
            errors.append(f"max_workers должен быть >= 1, получено: {config.max_workers}")
        
        # Проверка timeout
        if config.timeout <= 0:
            errors.append(f"timeout должен быть > 0, получено: {config.timeout}")
        
        # Проверка корректности host
        if not config.host or not isinstance(config.host, str):
            errors.append(f"host должен быть непустой строкой, получено: {config.host}")
        
        if errors:
            self._critical_error("Ошибки валидации конфигурации:\n" + "\n".join(f"  - {e}" for e in errors))
    
    def _critical_error(self, message: str) -> None:
        """
        Выводит критическую ошибку и завершает работу приложения.
        
        Args:
            message: Сообщение об ошибке
        """
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {message}", file=sys.stderr)
        print("Завершение работы приложения.", file=sys.stderr)
        sys.exit(1)


def init_app() -> Config:
    """
    Инициализирует приложение, загружая конфигурацию.
    
    Returns:
        Config: Загруженная и валидированная конфигурация
    """
    print("Инициализация приложения...")
    
    # Пробуем несколько возможных путей к конфигурации
    possible_paths = [
        "config.json",
        Path.home() / ".config" / "myapp" / "config.json",
        "/etc/myapp/config.json",
    ]
    
    for config_path in possible_paths:
        loader = ConfigLoader(config_path)
        if loader.config_path.exists():
            return loader.load()
    
    # Если ни один файл не найден, используем конфигурацию по умолчанию
    print("Файлы конфигурации не найдены. Используются значения по умолчанию.")
    loader = ConfigLoader()
    return loader.load()