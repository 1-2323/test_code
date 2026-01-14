import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, TypeVar, Generic
from dataclasses import dataclass, field
from enum import Enum

T = TypeVar('T')

class ConfigError(Exception):
    """Базовое исключение для ошибок конфигурации."""
    pass

class ConfigFileNotFoundError(ConfigError):
    """Исключение для случая, когда файл конфигурации не найден."""
    pass

class ConfigValidationError(ConfigError):
    """Исключение для ошибок валидации конфигурации."""
    pass

class MergeStrategy(Enum):
    """Стратегии слияния конфигураций."""
    REPLACE = "replace"      # Заменить значения
    MERGE = "merge"          # Рекурсивное слияние словарей
    EXTEND = "extend"        # Объединение списков

@dataclass
class ConfigMetadata:
    """Метаданные конфигурации."""
    source_file: Optional[str] = None
    last_modified: Optional[float] = None
    checksum: Optional[str] = None
    environment: str = "default"

class ConfigurationLoader(Generic[T]):
    """Загрузчик конфигурации из JSON файлов с fallback-значениями."""
    
    def __init__(
        self,
        config_schema: Optional[Dict[str, Any]] = None,
        default_values: Optional[Dict[str, Any]] = None,
        env_prefix: str = "APP_",
        required_keys: Optional[List[str]] = None,
        merge_strategy: MergeStrategy = MergeStrategy.MERGE
    ):
        """
        Инициализация загрузчика конфигурации.
        
        Args:
            config_schema: Схема конфигурации с типами значений
            default_values: Значения по умолчанию
            env_prefix: Префикс для переменных окружения
            required_keys: Обязательные ключи конфигурации
            merge_strategy: Стратегия слияния конфигураций
        """
        self.config_schema = config_schema or {}
        self.default_values = default_values or {}
        self.env_prefix = env_prefix
        self.required_keys = required_keys or []
        self.merge_strategy = merge_strategy
        self._config: Dict[str, Any] = {}
        self._metadata: ConfigMetadata = ConfigMetadata()
        self._validators = {
            'string': self._validate_string,
            'integer': self._validate_integer,
            'float': self._validate_float,
            'boolean': self._validate_boolean,
            'list': self._validate_list,
            'dict': self._validate_dict
        }
    
    def _validate_string(self, value: Any) -> str:
        """Валидация строкового значения."""
        if not isinstance(value, str):
            raise ConfigValidationError(f"Expected string, got {type(value).__name__}")
        return str(value)
    
    def _validate_integer(self, value: Any) -> int:
        """Валидация целочисленного значения."""
        try:
            return int(value)
        except (ValueError, TypeError):
            raise ConfigValidationError(f"Expected integer, got {type(value).__name__}")
    
    def _validate_float(self, value: Any) -> float:
        """Валидация значения с плавающей точкой."""
        try:
            return float(value)
        except (ValueError, TypeError):
            raise ConfigValidationError(f"Expected float, got {type(value).__name__}")
    
    def _validate_boolean(self, value: Any) -> bool:
        """Валидация булевого значения."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ('true', 'yes', '1', 'on'):
                return True
            if value.lower() in ('false', 'no', '0', 'off'):
                return False
        raise ConfigValidationError(f"Expected boolean, got {type(value).__name__}")
    
    def _validate_list(self, value: Any) -> list:
        """Валидация списка."""
        if not isinstance(value, list):
            raise ConfigValidationError(f"Expected list, got {type(value).__name__}")
        return value
    
    def _validate_dict(self, value: Any) -> dict:
        """Валидация словаря."""
        if not isinstance(value, dict):
            raise ConfigValidationError(f"Expected dict, got {type(value).__name__}")
        return value
    
    def _validate_value(self, key: str, value: Any) -> Any:
        """Валидация значения по схеме."""
        if key in self.config_schema:
            schema = self.config_schema[key]
            
            if isinstance(schema, dict):
                # Сложная схема с типом и валидаторами
                expected_type = schema.get('type')
                if expected_type in self._validators:
                    validated_value = self._validators[expected_type](value)
                    
                    # Дополнительные проверки
                    if 'min' in schema and isinstance(validated_value, (int, float)):
                        if validated_value < schema['min']:
                            raise ConfigValidationError(
                                f"Value for '{key}' must be >= {schema['min']}"
                            )
                    
                    if 'max' in schema and isinstance(validated_value, (int, float)):
                        if validated_value > schema['max']:
                            raise ConfigValidationError(
                                f"Value for '{key}' must be <= {schema['max']}"
                            )
                    
                    if 'choices' in schema and isinstance(schema['choices'], list):
                        if validated_value not in schema['choices']:
                            raise ConfigValidationError(
                                f"Value for '{key}' must be one of {schema['choices']}"
                            )
                    
                    return validated_value
            elif isinstance(schema, type):
                # Простая проверка типа
                if not isinstance(value, schema):
                    try:
                        return schema(value)
                    except (ValueError, TypeError):
                        raise ConfigValidationError(
                            f"Expected {schema.__name__} for '{key}', got {type(value).__name__}"
                        )
        
        return value
    
    def _merge_dicts(self, dict1: Dict, dict2: Dict, strategy: MergeStrategy) -> Dict:
        """Рекурсивное слияние двух словарей."""
        result = deepcopy(dict1)
        
        for key, value in dict2.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Рекурсивное слияние вложенных словарей
                result[key] = self._merge_dicts(result[key], value, strategy)
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                # Обработка списков
                if strategy == MergeStrategy.EXTEND:
                    result[key] = result[key] + value
                elif strategy == MergeStrategy.REPLACE:
                    result[key] = value
                else:  # MERGE - уникальные элементы
                    result[key] = list(set(result[key] + value))
            else:
                # Замена или добавление значения
                result[key] = value
        
        return result
    
    def _load_from_env(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Загрузка значений из переменных окружения."""
        env_config = {}
        
        for key, value in config.items():
            env_key = f"{self.env_prefix}{key.upper().replace('.', '_')}"
            
            if env_key in os.environ:
                env_value = os.environ[env_key]
                
                # Попытка преобразования типов
                if isinstance(value, bool):
                    env_config[key] = env_value.lower() in ('true', 'yes', '1', 'on')
                elif isinstance(value, int):
                    try:
                        env_config[key] = int(env_value)
                    except ValueError:
                        env_config[key] = value
                elif isinstance(value, float):
                    try:
                        env_config[key] = float(env_value)
                    except ValueError:
                        env_config[key] = value
                elif isinstance(value, list):
                    # Списки из переменных окружения (через запятую)
                    env_config[key] = [v.strip() for v in env_value.split(',')]
                else:
                    env_config[key] = env_value
        
        return env_config
    
    def _resolve_nested_keys(self, flat_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Преобразование плоского словаря во вложенный."""
        result = {}
        
        for key, value in flat_dict.items():
            keys = key.split('.')
            current = result
            
            for i, k in enumerate(keys[:-1]):
                if k not in current:
                    current[k] = {}
                current = current[k]
            
            current[keys[-1]] = value
        
        return result
    
    def load_from_file(
        self,
        file_path: Union[str, Path],
        required: bool = True,
        encoding: str = 'utf-8'
    ) -> 'ConfigurationLoader':
        """
        Загрузка конфигурации из JSON файла.
        
        Args:
            file_path: Путь к файлу конфигурации
            required: Обязательно ли наличие файла
            encoding: Кодировка файла
            
        Returns:
            self для цепочки вызовов
        """
        path = Path(file_path)
        
        if not path.exists():
            if required:
                raise ConfigFileNotFoundError(f"Config file not found: {file_path}")
            return self
        
        try:
            with open(path, 'r', encoding=encoding) as f:
                file_config = json.load(f)
            
            # Обновляем метаданные
            self._metadata.source_file = str(path.absolute())
            self._metadata.last_modified = path.stat().st_mtime
            
            # Слияние с текущей конфигурацией
            self._config = self._merge_dicts(
                self._config,
                file_config,
                self.merge_strategy
            )
            
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            raise ConfigError(f"Error loading config file: {e}")
        
        return self
    
    def load_from_dict(self, config_dict: Dict[str, Any]) -> 'ConfigurationLoader':
        """
        Загрузка конфигурации из словаря.
        
        Args:
            config_dict: Словарь с конфигурацией
            
        Returns:
            self для цепочки вызовов
        """
        self._config = self._merge_dicts(
            self._config,
            config_dict,
            self.merge_strategy
        )
        return self
    
    def load_from_env(self) -> 'ConfigurationLoader':
        """Загрузка конфигурации из переменных окружения."""
        env_config = self._load_from_env(self._config)
        nested_env_config = self._resolve_nested_keys(env_config)
        
        self._config = self._merge_dicts(
            self._config,
            nested_env_config,
            MergeStrategy.REPLACE  # Переменные окружения имеют высший приоритет
        )
        return self
    
    def apply_defaults(self) -> 'ConfigurationLoader':
        """Применение значений по умолчанию."""
        # Сначала применяем defaults, затем перезаписываем загруженными значениями
        merged = self._merge_dicts(
            self.default_values,
            self._config,
            MergeStrategy.REPLACE
        )
        self._config = merged
        return self
    
    def validate(self) -> 'ConfigurationLoader':
        """Валидация конфигурации по схеме."""
        # Проверка обязательных ключей
        for key in self.required_keys:
            if key not in self._config:
                raise ConfigValidationError(f"Missing required configuration key: {key}")
        
        # Валидация значений по схеме
        for key, value in self._config.items():
            try:
                self._config[key] = self._validate_value(key, value)
            except ConfigValidationError as e:
                raise ConfigValidationError(f"Validation failed for '{key}': {e}")
        
        return self
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Получение значения по ключу с поддержкой вложенных ключей через точку.
        
        Args:
            key: Ключ конфигурации (например, 'database.host')
            default: Значение по умолчанию, если ключ не найден
            
        Returns:
            Значение конфигурации
        """
        keys = key.split('.')
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any) -> None:
        """
        Установка значения по ключу с поддержкой вложенных ключей.
        
        Args:
            key: Ключ конфигурации
            value: Значение
        """
        keys = key.split('.')
        current = self._config
        
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        
        current[keys[-1]] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """Возвращает конфигурацию в виде словаря."""
        return deepcopy(self._config)
    
    def save_to_file(
        self,
        file_path: Union[str, Path],
        indent: int = 2,
        encoding: str = 'utf-8'
    ) -> None:
        """
        Сохранение конфигурации в JSON файл.
        
        Args:
            file_path: Путь для сохранения
            indent: Отступ в JSON файле
            encoding: Кодировка файла
        """
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding=encoding) as f:
            json.dump(self._config, f, indent=indent, ensure_ascii=False)
    
    def reload(self) -> None:
        """Перезагрузка конфигурации из исходного файла."""
        if self._metadata.source_file:
            self._config = {}
            self.load_from_file(self._metadata.source_file)
            self.apply_defaults()
            self.load_from_env()
            self.validate()
    
    @property
    def metadata(self) -> ConfigMetadata:
        """Метаданные конфигурации."""
        return self._metadata
    
    def __getitem__(self, key: str) -> Any:
        """Получение значения через оператор []."""
        return self.get(key)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Установка значения через оператор []."""
        self.set(key, value)
    
    def __contains__(self, key: str) -> bool:
        """Проверка наличия ключа."""
        try:
            self.get(key)
            return True
        except (KeyError, TypeError):
            return False
    
    @classmethod
    def from_files(
        cls,
        files: List[Union[str, Path]],
        default_file: Optional[Union[str, Path]] = None,
        **kwargs
    ) -> 'ConfigurationLoader':
        """
        Создание загрузчика из нескольких файлов конфигурации.
        
        Args:
            files: Список файлов конфигурации (от низшего к высшему приоритету)
            default_file: Файл с значениями по умолчанию
            **kwargs: Дополнительные параметры для конструктора
            
        Returns:
            Загруженная конфигурация
        """
        loader = cls(**kwargs)
        
        # Загрузка значений по умолчанию
        if default_file:
            loader.load_from_file(default_file, required=False)
        
        loader.apply_defaults()
        
        # Загрузка основной конфигурации (от низшего к высшему приоритету)
        for config_file in files:
            loader.load_from_file(config_file, required=False)
        
        # Переменные окружения имеют высший приоритет
        loader.load_from_env()
        
        # Валидация
        loader.validate()
        
        return loader