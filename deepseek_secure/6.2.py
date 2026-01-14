import yaml
import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from pathlib import Path

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Конфигурация базы данных"""
    host: str = "localhost"
    port: int = 5432
    name: str = "app_db"
    user: str = "postgres"
    password: str = ""
    pool_size: int = 10
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DatabaseConfig':
        """Создает конфигурацию из словаря"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class APIConfig:
    """Конфигурация API"""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    secret_key: str = "default-secret-key"
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'APIConfig':
        """Создает конфигурацию из словаря"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CacheConfig:
    """Конфигурация кэша"""
    enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    default_ttl: int = 300
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheConfig':
        """Создает конфигурацию из словаря"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AppConfig:
    """Основная конфигурация приложения"""
    app_name: str = "MyApplication"
    environment: str = "development"
    log_level: str = "INFO"
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    api: APIConfig = field(default_factory=APIConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    
    def apply_settings(self) -> None:
        """Применяет настройки конфигурации к приложению"""
        # Настройка логирования
        log_level = getattr(logging, self.log_level.upper(), logging.INFO)
        logging.getLogger().setLevel(log_level)
        
        logger.info(f"Приложение '{self.app_name}' запущено в среде '{self.environment}'")
        logger.info(f"Уровень логирования установлен: {self.log_level}")
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AppConfig':
        """Создает конфигурацию приложения из словаря"""
        config_data = data.copy()
        
        # Создаем вложенные конфигурации
        if 'database' in config_data:
            config_data['database'] = DatabaseConfig.from_dict(config_data['database'])
        
        if 'api' in config_data:
            config_data['api'] = APIConfig.from_dict(config_data['api'])
        
        if 'cache' in config_data:
            config_data['cache'] = CacheConfig.from_dict(config_data['cache'])
        
        # Возвращаем только известные поля
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in config_data.items() if k in known_fields}
        
        return cls(**filtered_data)


class ConfigLoader:
    """Загрузчик конфигурации из YAML файлов"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Инициализация загрузчика конфигурации
        
        Args:
            config_path: Путь к файлу конфигурации. Если None, используется значение по умолчанию.
        """
        self.config_path = Path(config_path) if config_path else self._get_default_config_path()
        
    def _get_default_config_path(self) -> Path:
        """Возвращает путь к файлу конфигурации по умолчанию"""
        paths = [
            Path("config.yaml"),
            Path("config.yml"),
            Path("config", "config.yaml"),
            Path("config", "config.yml"),
        ]
        
        for path in paths:
            if path.exists():
                return path
        
        # Если файл не найден, возвращаем путь по умолчанию
        return Path("config.yaml")
    
    def load(self) -> AppConfig:
        """
        Загружает конфигурацию из YAML файла
        
        Returns:
            Экземпляр AppConfig с загруженными настройками
            
        Raises:
            FileNotFoundError: Если файл конфигурации не найден
            yaml.YAMLError: Если произошла ошибка парсинга YAML
        """
        if not self.config_path.exists():
            logger.warning(f"Файл конфигурации {self.config_path} не найден. Используются значения по умолчанию.")
            return AppConfig()
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as file:
                # Используем safe_load() для предотвращения выполнения произвольного кода
                config_data = yaml.safe_load(file)
                
            if config_data is None:
                logger.warning("Файл конфигурации пуст. Используются значения по умолчанию.")
                return AppConfig()
            
            logger.info(f"Конфигурация загружена из {self.config_path}")
            return AppConfig.from_dict(config_data)
            
        except yaml.YAMLError as e:
            logger.error(f"Ошибка парсинга YAML в файле {self.config_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Неожиданная ошибка при загрузке конфигурации: {e}")
            raise
    
    def load_and_apply(self) -> AppConfig:
        """
        Загружает конфигурацию и применяет настройки к приложению
        
        Returns:
            Экземпляр AppConfig с примененными настройками
        """
        config = self.load()
        config.apply_settings()
        return config


def create_app_with_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Фабричная функция для создания приложения с загруженной конфигурацией
    
    Args:
        config_path: Путь к файлу конфигурации
        
    Returns:
        Экземпляр AppConfig
    """
    loader = ConfigLoader(config_path)
    return loader.load_and_apply()