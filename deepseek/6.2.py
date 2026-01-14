import yaml
import os
import logging
from typing import Any, Dict, Optional, Type, TypeVar, Union
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

T = TypeVar('T')

class ConfigError(Exception):
    """Базовое исключение для ошибок конфигурации."""
    pass

class ConfigValidationError(ConfigError):
    """Исключение для ошибок валидации конфигурации."""
    pass

class EnvironmentVariableNotFound(ConfigError):
    """Исключение для отсутствующих переменных окружения."""
    pass

class ConfigSource(Enum):
    """Источник значения конфигурации."""
    FILE = "file"
    ENV = "environment"
    DEFAULT = "default"

@dataclass
class ConfigValue:
    """Контейнер для значения конфигурации с метаинформацией."""
    value: Any
    source: ConfigSource
    key_path: str
    env_var_name: Optional[str] = None

class ConfigLoader:
    """
    Загрузчик YAML-конфигурации с поддержкой переменных окружения,
    валидацией и применением настроек.
    """
    
    def __init__(
        self,
        config_path: Union[str, Path],
        env_prefix: str = "APP_",
        strict_validation: bool = True,
        auto_cast_types: bool = True
    ):
        """
        Инициализация загрузчика конфигурации.
        
        Args:
            config_path: Путь к YAML-файлу конфигурации
            env_prefix: Префикс для переменных окружения
            strict_validation: Строгая валидация (выбрасывает исключения)
            auto_cast_types: Автоматическое приведение типов
        """
        self.config_path = Path(config_path)
        self.env_prefix = env_prefix
        self.strict_validation = strict_validation
        self.auto_cast_types = auto_cast_types
        self._raw_config: Dict[str, Any] = {}
        self._parsed_config: Dict[str, ConfigValue] = {}
        self._applied_config: Dict[str, Any] = {}
        self._logger = self._setup_logger()
        
    def _setup_logger(self) -> logging.Logger:
        """Настройка логгера."""
        logger = logging.getLogger(__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger
    
    def load(self) -> 'ConfigLoader':
        """
        Загружает и парсит конфигурацию.
        
        Returns:
            self для цепочки вызовов
        """
        try:
            self._validate_config_path()
            self._load_yaml_config()
            self._parse_config_values()
            self._logger.info(f"Конфигурация успешно загружена из {self.config_path}")
            return self
        except Exception as e:
            self._logger.error(f"Ошибка загрузки конфигурации: {e}")
            if self.strict_validation:
                raise
            return self
    
    def _validate_config_path(self) -> None:
        """Проверяет существование и доступность файла конфигурации."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Файл конфигурации не найден: {self.config_path}"
            )
        if not self.config_path.is_file():
            raise ConfigError(
                f"Путь не является файлом: {self.config_path}"
            )
        if not os.access(self.config_path, os.R_OK):
            raise ConfigError(
                f"Нет прав на чтение файла: {self.config_path}"
            )
    
    def _load_yaml_config(self) -> None:
        """Загружает YAML-конфигурацию из файла."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._raw_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"Ошибка парсинга YAML: {e}")
    
    def _parse_config_values(self, data: Optional[Dict] = None, prefix: str = "") -> None:
        """
        Рекурсивно парсит значения конфигурации с учетом переменных окружения.
        
        Args:
            data: Данные для парсинга (по умолчанию - весь конфиг)
            prefix: Префикс для ключей (для вложенных структур)
        """
        if data is None:
            data = self._raw_config
        
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            env_key = self._key_to_env_var(full_key)
            
            if isinstance(value, dict):
                # Рекурсивный парсинг вложенных словарей
                self._parse_config_values(value, full_key)
            else:
                # Парсинг простых значений
                config_value = self._resolve_value(full_key, value, env_key)
                self._parsed_config[full_key] = config_value
    
    def _key_to_env_var(self, key: str) -> str:
        """Преобразует ключ конфигурации в имя переменной окружения."""
        # Заменяем точки на подчеркивания и приводим к верхнему регистру
        env_key = key.replace('.', '_').upper()
        return f"{self.env_prefix}{env_key}"
    
    def _resolve_value(self, key: str, file_value: Any, env_key: str) -> ConfigValue:
        """
        Разрешает значение конфигурации с приоритетом:
        1. Переменная окружения
        2. Значение из файла
        3. Значение по умолчанию (если есть)
        
        Args:
            key: Полный ключ конфигурации
            file_value: Значение из файла
            env_key: Имя переменной окружения
            
        Returns:
            ConfigValue с разрешенным значением
        """
        # Проверяем переменную окружения
        env_value = os.environ.get(env_key)
        
        if env_value is not None:
            self._logger.debug(f"Используется переменная окружения для {key}: {env_key}")
            try:
                casted_value = self._cast_value(key, env_value, file_value)
                return ConfigValue(
                    value=casted_value,
                    source=ConfigSource.ENV,
                    key_path=key,
                    env_var_name=env_key
                )
            except Exception as e:
                self._logger.warning(
                    f"Не удалось привести переменную окружения {env_key}: {e}"
                )
                if self.strict_validation:
                    raise ConfigValidationError(
                        f"Ошибка приведения типа для {env_key}: {e}"
                    )
        
        # Используем значение из файла
        return ConfigValue(
            value=file_value,
            source=ConfigSource.FILE,
            key_path=key
        )
    
    def _cast_value(self, key: str, value: str, original_value: Any) -> Any:
        """
        Приводит значение к типу оригинального значения из конфига.
        
        Args:
            key: Ключ конфигурации
            value: Значение для приведения
            original_value: Оригинальное значение (для определения типа)
            
        Returns:
            Приведенное значение
        """
        if not self.auto_cast_types:
            return value
        
        try:
            if isinstance(original_value, bool):
                # Обработка булевых значений
                if value.lower() in ('true', 'yes', '1', 'on'):
                    return True
                elif value.lower() in ('false', 'no', '0', 'off'):
                    return False
                raise ValueError(f"Недопустимое булево значение: {value}")
            
            elif isinstance(original_value, int):
                return int(value)
            
            elif isinstance(original_value, float):
                return float(value)
            
            elif isinstance(original_value, list):
                # Обработка списков (разделитель - запятая)
                if isinstance(value, str):
                    return [item.strip() for item in value.split(',') if item.strip()]
                return value
            
            elif isinstance(original_value, dict):
                # Для словарей пытаемся парсить JSON/YAML
                try:
                    return yaml.safe_load(value)
                except:
                    return value
            
            else:
                # Для строк и других типов возвращаем как есть
                return value
                
        except (ValueError, TypeError) as e:
            raise ConfigValidationError(
                f"Ошибка приведения типа для ключа '{key}': {e}"
            )
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Получает значение конфигурации по ключу.
        
        Args:
            key: Ключ конфигурации (с точками для вложенности)
            default: Значение по умолчанию
            
        Returns:
            Значение конфигурации или default
        """
        config_value = self._parsed_config.get(key)
        if config_value:
            return config_value.value
        return default
    
    def get_config_value(self, key: str) -> Optional[ConfigValue]:
        """
        Получает объект ConfigValue по ключу.
        
        Args:
            key: Ключ конфигурации
            
        Returns:
            ConfigValue или None
        """
        return self._parsed_config.get(key)
    
    def get_all(self, flatten: bool = True) -> Dict[str, Any]:
        """
        Возвращает все значения конфигурации.
        
        Args:
            flatten: Если True, возвращает плоский словарь
            
        Returns:
            Словарь со всеми значениями конфигурации
        """
        if flatten:
            return {k: v.value for k, v in self._parsed_config.items()}
        
        # Восстанавливаем вложенную структуру
        result = {}
        for key, config_value in self._parsed_config.items():
            self._set_nested_value(result, key.split('.'), config_value.value)
        return result
    
    def _set_nested_value(self, data: Dict, keys: list, value: Any) -> None:
        """Устанавливает значение во вложенном словаре."""
        current = data
        for i, key in enumerate(keys[:-1]):
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value
    
    def validate(self, validation_rules: Dict[str, Any]) -> bool:
        """
        Валидирует конфигурацию по заданным правилам.
        
        Args:
            validation_rules: Правила валидации
            
        Returns:
            True если валидация прошла успешно
        """
        errors = []
        
        for key, rule in validation_rules.items():
            value = self.get(key)
            
            if value is None:
                errors.append(f"Отсутствует обязательный параметр: {key}")
                continue
            
            if isinstance(rule, type):
                # Проверка типа
                if not isinstance(value, rule):
                    errors.append(
                        f"Неверный тип для {key}: ожидался {rule}, получен {type(value)}"
                    )
            
            elif callable(rule):
                # Пользовательская функция валидации
                try:
                    if not rule(value):
                        errors.append(f"Не пройдена валидация для {key}: {rule.__name__}")
                except Exception as e:
                    errors.append(f"Ошибка валидации для {key}: {e}")
            
            elif isinstance(rule, (list, tuple)):
                # Проверка на вхождение в список допустимых значений
                if value not in rule:
                    errors.append(
                        f"Недопустимое значение для {key}: {value}. "
                        f"Допустимые значения: {rule}"
                    )
        
        if errors:
            self._logger.warning(f"Ошибки валидации конфигурации: {errors}")
            if self.strict_validation:
                raise ConfigValidationError("\n".join(errors))
            return False
        
        self._logger.info("Конфигурация прошла валидацию")
        return True
    
    def apply_to_app(self, app_object: Any, attribute_prefix: str = "") -> None:
        """
        Применяет конфигурацию к объекту приложения.
        
        Args:
            app_object: Объект приложения
            attribute_prefix: Префикс для атрибутов
        """
        if not hasattr(app_object, '__dict__'):
            raise ConfigError("Объект приложения должен иметь атрибуты")
        
        applied_count = 0
        for key, config_value in self._parsed_config.items():
            attr_name = self._key_to_attribute(key, attribute_prefix)
            
            try:
                if hasattr(app_object, attr_name):
                    current_value = getattr(app_object, attr_name)
                    
                    # Не перезаписываем атрибуты, которые уже были установлены
                    if current_value is not None and not self._is_default_value(current_value):
                        self._logger.debug(
                            f"Пропуск атрибута {attr_name}: уже установлен"
                        )
                        continue
                    
                    setattr(app_object, attr_name, config_value.value)
                    self._applied_config[attr_name] = config_value
                    applied_count += 1
                    
                    self._logger.debug(
                        f"Установлен атрибут {attr_name} = {config_value.value} "
                        f"(источник: {config_value.source.value})"
                    )
                else:
                    self._logger.warning(
                        f"Атрибут {attr_name} не найден в объекте приложения"
                    )
            except AttributeError as e:
                self._logger.error(f"Ошибка установки атрибута {attr_name}: {e}")
                if self.strict_validation:
                    raise
        
        self._logger.info(f"Применено {applied_count} параметров конфигурации к приложению")
    
    def _key_to_attribute(self, key: str, prefix: str = "") -> str:
        """Преобразует ключ конфигурации в имя атрибута."""
        # Преобразуем some.config.value в some_config_value
        attr_name = key.replace('.', '_')
        if prefix:
            attr_name = f"{prefix}_{attr_name}"
        return attr_name.lower()
    
    def _is_default_value(self, value: Any) -> bool:
        """Проверяет, является ли значение значением по умолчанию."""
        default_values = [None, '', [], {}, 0]
        return value in default_values
    
    def reload(self) -> None:
        """Перезагружает конфигурацию."""
        self._logger.info("Перезагрузка конфигурации...")
        self._raw_config.clear()
        self._parsed_config.clear()
        self._applied_config.clear()
        self.load()
    
    def dump_to_yaml(self, output_path: Union[str, Path]) -> None:
        """
        Сохраняет текущую конфигурацию в YAML-файл.
        
        Args:
            output_path: Путь для сохранения
        """
        config_dict = self.get_all(flatten=False)
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
            self._logger.info(f"Конфигурация сохранена в {output_path}")
        except Exception as e:
            self._logger.error(f"Ошибка сохранения конфигурации: {e}")
            if self.strict_validation:
                raise
    
    def get_applied_config(self) -> Dict[str, ConfigValue]:
        """Возвращает примененную конфигурацию."""
        return self._applied_config.copy()
    
    @property
    def sources_summary(self) -> Dict[str, int]:
        """Сводка по источникам конфигурации."""
        summary = {source.value: 0 for source in ConfigSource}
        
        for config_value in self._parsed_config.values():
            summary[config_value.source.value] += 1
        
        return summary