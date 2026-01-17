import json
import yaml
import hashlib
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import sqlite3
from contextlib import contextmanager
import logging
from pathlib import Path
import difflib
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConfigFormat(str, Enum):
    """Форматы конфигурационных файлов."""
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    XML = "xml"
    INI = "ini"


class ChangeType(str, Enum):
    """Типы изменений конфигурации."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    ROLLBACK = "rollback"


@dataclass
class ConfigVersion:
    """Версия конфигурации."""
    id: str
    config_id: str
    version: int
    content: Dict[str, Any]
    hash: str
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = "system"
    comment: Optional[str] = None
    change_type: ChangeType = ChangeType.UPDATED
    parent_version: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'id': self.id,
            'config_id': self.config_id,
            'version': self.version,
            'content': self.content,
            'hash': self.hash,
            'created_at': self.created_at.isoformat(),
            'created_by': self.created_by,
            'comment': self.comment,
            'change_type': self.change_type.value,
            'parent_version': self.parent_version
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigVersion':
        """Десериализация из словаря."""
        return cls(
            id=data['id'],
            config_id=data['config_id'],
            version=data['version'],
            content=data['content'],
            hash=data['hash'],
            created_at=datetime.fromisoformat(data['created_at']),
            created_by=data['created_by'],
            comment=data.get('comment'),
            change_type=ChangeType(data['change_type']),
            parent_version=data.get('parent_version')
        )


@dataclass
class ConfigDiff:
    """Разница между двумя версиями конфигурации."""
    from_version: int
    to_version: int
    changes: List[Dict[str, Any]]
    added_keys: List[str]
    removed_keys: List[str]
    modified_keys: List[str]
    diff_text: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'from_version': self.from_version,
            'to_version': self.to_version,
            'changes': self.changes,
            'added_keys': self.added_keys,
            'removed_keys': self.removed_keys,
            'modified_keys': self.modified_keys,
            'diff_text': self.diff_text
        }


class ConfigValidator:
    """Валидатор конфигураций."""
    
    def __init__(self, schema_registry: Optional[Dict[str, Any]] = None):
        """
        Инициализация валидатора.
        
        Args:
            schema_registry: Реестр JSON схем
        """
        self.schema_registry = schema_registry or {}
    
    def register_schema(self, config_type: str, schema: Dict[str, Any]) -> None:
        """
        Регистрация JSON схемы для типа конфигурации.
        
        Args:
            config_type: Тип конфигурации
            schema: JSON схема
        """
        self.schema_registry[config_type] = schema
        logger.info(f"Registered schema for config type: {config_type}")
    
    def validate(self, config: Dict[str, Any], schema: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Валидация конфигурации по JSON схеме.
        
        Args:
            config: Конфигурация для валидации
            schema: JSON схема
            
        Returns:
            (валидна, список ошибок)
        """
        errors = []
        
        try:
            # Простая валидация (в реальном проекте используйте jsonschema)
            self._validate_recursive(config, schema, "", errors)
        except Exception as e:
            errors.append(f"Validation error: {str(e)}")
        
        return len(errors) == 0, errors
    
    def _validate_recursive(self, data: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
        """
        Рекурсивная валидация.
        
        Args:
            data: Данные для валидации
            schema: Схема валидации
            path: Текущий путь в конфигурации
            errors: Список ошибок
        """
        if 'type' in schema:
            expected_type = schema['type']
            
            if expected_type == 'object':
                if not isinstance(data, dict):
                    errors.append(f"{path}: Expected object, got {type(data).__name__}")
                    return
                
                # Проверка обязательных полей
                required_fields = schema.get('required', [])
                for field in required_fields:
                    if field not in data:
                        errors.append(f"{path}.{field}: Required field is missing")
                
                # Проверка свойств
                properties = schema.get('properties', {})
                for key, value in data.items():
                    if key in properties:
                        self._validate_recursive(value, properties[key], f"{path}.{key}", errors)
                    elif schema.get('additionalProperties', True) is False:
                        errors.append(f"{path}.{key}: Additional property not allowed")
            
            elif expected_type == 'array':
                if not isinstance(data, list):
                    errors.append(f"{path}: Expected array, got {type(data).__name__}")
                    return
                
                items_schema = schema.get('items', {})
                for i, item in enumerate(data):
                    self._validate_recursive(item, items_schema, f"{path}[{i}]", errors)
            
            else:
                # Проверка простых типов
                type_check = {
                    'string': lambda x: isinstance(x, str),
                    'number': lambda x: isinstance(x, (int, float)),
                    'integer': lambda x: isinstance(x, int),
                    'boolean': lambda x: isinstance(x, bool),
                    'null': lambda x: x is None
                }
                
                if expected_type in type_check:
                    if not type_check[expected_type](data):
                        errors.append(f"{path}: Expected {expected_type}, got {type(data).__name__}")
        
        # Проверка enum
        if 'enum' in schema:
            if data not in schema['enum']:
                errors.append(f"{path}: Value must be one of {schema['enum']}")
        
        # Проверка диапазонов
        if isinstance(data, (int, float)):
            if 'minimum' in schema and data < schema['minimum']:
                errors.append(f"{path}: Value must be >= {schema['minimum']}")
            if 'maximum' in schema and data > schema['maximum']:
                errors.append(f"{path}: Value must be <= {schema['maximum']}")
            if 'exclusiveMinimum' in schema and data <= schema['exclusiveMinimum']:
                errors.append(f"{path}: Value must be > {schema['exclusiveMinimum']}")
            if 'exclusiveMaximum' in schema and data >= schema['exclusiveMaximum']:
                errors.append(f"{path}: Value must be < {schema['exclusiveMaximum']}")


class ConfigParser:
    """Парсер конфигурационных файлов."""
    
    @staticmethod
    def parse(content: str, format: ConfigFormat) -> Dict[str, Any]:
        """
        Парсинг конфигурационного файла.
        
        Args:
            content: Содержимое файла
            format: Формат файла
            
        Returns:
            Распарсенный словарь конфигурации
            
        Raises:
            ValueError: Если формат не поддерживается или ошибка парсинга
        """
        try:
            if format == ConfigFormat.JSON:
                return json.loads(content)
            elif format == ConfigFormat.YAML:
                return yaml.safe_load(content)
            elif format == ConfigFormat.TOML:
                import tomli
                return tomli.loads(content)
            elif format == ConfigFormat.INI:
                import configparser
                parser = configparser.ConfigParser()
                parser.read_string(content)
                return {s: dict(parser.items(s)) for s in parser.sections()}
            else:
                raise ValueError(f"Unsupported format: {format}")
        except Exception as e:
            raise ValueError(f"Failed to parse {format} config: {str(e)}")
    
    @staticmethod
    def serialize(config: Dict[str, Any], format: ConfigFormat) -> str:
        """
        Сериализация конфигурации в строку.
        
        Args:
            config: Конфигурация
            format: Целевой формат
            
        Returns:
            Сериализованная строка
        """
        if format == ConfigFormat.JSON:
            return json.dumps(config, indent=2, ensure_ascii=False)
        elif format == ConfigFormat.YAML:
            return yaml.dump(config, default_flow_style=False, allow_unicode=True)
        elif format == ConfigFormat.TOML:
            import toml
            return toml.dumps(config)
        else:
            raise ValueError(f"Unsupported serialization format: {format}")


class ConfigHashCalculator:
    """Калькулятор хешей конфигураций."""
    
    @staticmethod
    def calculate_hash(config: Dict[str, Any]) -> str:
        """
        Вычисление хеша конфигурации.
        
        Args:
            config: Конфигурация
            
        Returns:
            SHA256 хеш
        """
        # Нормализуем конфигурацию для стабильного хеширования
        normalized = ConfigHashCalculator._normalize_config(config)
        json_str = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
        
        return hashlib.sha256(json_str.encode()).hexdigest()
    
    @staticmethod
    def _normalize_config(config: Any) -> Any:
        """
        Нормализация конфигурации для хеширования.
        
        Args:
            config: Конфигурация
            
        Returns:
            Нормализованная конфигурация
        """
        if isinstance(config, dict):
            return {k: ConfigHashCalculator._normalize_config(v) 
                   for k, v in sorted(config.items())}
        elif isinstance(config, list):
            return [ConfigHashCalculator._normalize_config(item) for item in config]
        elif isinstance(config, float):
            # Нормализуем float для избежания проблем с точностью
            return round(config, 10)
        else:
            return config


class ConfigDiffCalculator:
    """Калькулятор различий между конфигурациями."""
    
    @staticmethod
    def calculate_diff(old_config: Dict[str, Any], new_config: Dict[str, Any]) -> ConfigDiff:
        """
        Вычисление различий между двумя конфигурациями.
        
        Args:
            old_config: Старая конфигурация
            new_config: Новая конфигурация
            
        Returns:
            Объект с различиями
        """
        changes = []
        added_keys = []
        removed_keys = []
        modified_keys = []
        
        # Сравниваем ключи
        old_keys = set(ConfigDiffCalculator._flatten_dict(old_config).keys())
        new_keys = set(ConfigDiffCalculator._flatten_dict(new_config).keys())
        
        added_keys = list(new_keys - old_keys)
        removed_keys = list(old_keys - new_keys)
        common_keys = old_keys & new_keys
        
        # Находим измененные значения
        for key in common_keys:
            old_value = ConfigDiffCalculator._get_nested_value(old_config, key)
            new_value = ConfigDiffCalculator._get_nested_value(new_config, key)
            
            if old_value != new_value:
                modified_keys.append(key)
                changes.append({
                    'key': key,
                    'old_value': old_value,
                    'new_value': new_value,
                    'change_type': 'modified'
                })
        
        # Форматируем diff в текстовом виде
        old_str = json.dumps(old_config, indent=2, sort_keys=True)
        new_str = json.dumps(new_config, indent=2, sort_keys=True)
        diff_text = "\n".join(difflib.unified_diff(
            old_str.splitlines(),
            new_str.splitlines(),
            lineterm='',
            fromfile='old',
            tofile='new'
        ))
        
        return ConfigDiff(
            from_version=0,  # Заполнится позже
            to_version=0,    # Заполнится позже
            changes=changes,
            added_keys=added_keys,
            removed_keys=removed_keys,
            modified_keys=modified_keys,
            diff_text=diff_text
        )
    
    @staticmethod
    def _flatten_dict(d: Dict[str, Any], parent_key: str = '') -> Dict[str, Any]:
        """
        Преобразование вложенного словаря в плоский.
        
        Args:
            d: Словарь для преобразования
            parent_key: Родительский ключ
            
        Returns:
            Плоский словарь
        """
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            
            if isinstance(v, dict):
                items.extend(ConfigDiffCalculator._flatten_dict(v, new_key).items())
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        items.extend(
                            ConfigDiffCalculator._flatten_dict(item, f"{new_key}[{i}]").items()
                        )
                    else:
                        items.append((f"{new_key}[{i}]", item))
            else:
                items.append((new_key, v))
        
        return dict(items)
    
    @staticmethod
    def _get_nested_value(d: Dict[str, Any], key: str) -> Any:
        """
        Получение значения по пути в формате "key1.key2[0].key3".
        
        Args:
            d: Словарь
            key: Путь к значению
            
        Returns:
            Значение или None если не найдено
        """
        parts = re.split(r'[\.\[\]]', key)
        parts = [p for p in parts if p and not p.endswith(']')]
        
        current = d
        for part in parts:
            if ']' in part:
                # Обработка массивов
                array_part, index = part.split('[')
                index = int(index.rstrip(']'))
                current = current.get(array_part, [])
                if isinstance(current, list) and len(current) > index:
                    current = current[index]
                else:
                    return None
            else:
                current = current.get(part)
                if current is None:
                    return None
        
        return current


class ConfigStorage:
    """Хранилище конфигураций."""
    
    def __init__(self, db_path: str = "config_versions.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица конфигураций
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS configs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    format TEXT NOT NULL,
                    current_version INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT 'system',
                    is_active BOOLEAN DEFAULT TRUE,
                    tags TEXT  -- JSON массив тегов
                )
            """)
            
            # Таблица версий конфигураций
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS config_versions (
                    id TEXT PRIMARY KEY,
                    config_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content BLOB NOT NULL,
                    hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT NOT NULL,
                    comment TEXT,
                    change_type TEXT NOT NULL,
                    parent_version INTEGER,
                    UNIQUE(config_id, version),
                    FOREIGN KEY (config_id) REFERENCES configs(id) ON DELETE CASCADE
                )
            """)
            
            # Таблица деплойментов (когда конфигурация была применена)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deployments (
                    id TEXT PRIMARY KEY,
                    config_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deployed_by TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT,
                    FOREIGN KEY (config_id) REFERENCES configs(id) ON DELETE CASCADE
                )
            """)
            
            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_config_versions_config ON config_versions(config_id, version)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_config_versions_hash ON config_versions(hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_deployments_config ON deployments(config_id, environment)")
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для подключения к БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def create_config(
        self,
        name: str,
        content: Dict[str, Any],
        format: ConfigFormat = ConfigFormat.JSON,
        description: Optional[str] = None,
        created_by: str = "system",
        tags: Optional[List[str]] = None
    ) -> Tuple[str, int]:
        """
        Создание новой конфигурации.
        
        Args:
            name: Имя конфигурации
            content: Содержимое конфигурации
            format: Формат конфигурации
            description: Описание
            created_by: Автор
            tags: Теги
            
        Returns:
            (ID конфигурации, номер версии)
        """
        config_id = hashlib.md5(name.encode()).hexdigest()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем, существует ли уже конфигурация
            cursor.execute(
                "SELECT id FROM configs WHERE name = ?",
                (name,)
            )
            
            if cursor.fetchone():
                raise ValueError(f"Config '{name}' already exists")
            
            # Создаем запись конфигурации
            cursor.execute("""
                INSERT INTO configs 
                (id, name, description, format, created_by, tags)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                config_id,
                name,
                description,
                format.value,
                created_by,
                json.dumps(tags) if tags else None
            ))
            
            # Создаем первую версию
            version = 1
            version_id = self._create_version(
                config_id, version, content, created_by, 
                ChangeType.CREATED, None, conn
            )
            
            # Обновляем текущую версию
            cursor.execute("""
                UPDATE configs 
                SET current_version = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (version, config_id))
            
            conn.commit()
            
            logger.info(f"Created config '{name}' (id: {config_id}, version: {version})")
            return config_id, version
    
    def _create_version(
        self,
        config_id: str,
        version: int,
        content: Dict[str, Any],
        created_by: str,
        change_type: ChangeType,
        parent_version: Optional[int],
        conn: sqlite3.Connection
    ) -> str:
        """
        Создание версии конфигурации.
        
        Args:
            config_id: ID конфигурации
            version: Номер версии
            content: Содержимое
            created_by: Автор
            change_type: Тип изменения
            parent_version: Родительская версия
            conn: Подключение к БД
            
        Returns:
            ID версии
        """
        # Вычисляем хеш конфигурации
        config_hash = ConfigHashCalculator.calculate_hash(content)
        
        # Создаем ID версии
        version_id = f"{config_id}_v{version}"
        
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO config_versions 
            (id, config_id, version, content, hash, created_by, 
             comment, change_type, parent_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            version_id,
            config_id,
            version,
            json.dumps(content),
            config_hash,
            created_by,
            f"{change_type.value} version {version}",
            change_type.value,
            parent_version
        ))
        
        return version_id
    
    def update_config(
        self,
        config_id: str,
        content: Dict[str, Any],
        created_by: str = "system",
        comment: Optional[str] = None
    ) -> Tuple[Optional[int], bool]:
        """
        Обновление конфигурации.
        
        Args:
            config_id: ID конфигурации
            content: Новое содержимое
            created_by: Автор
            comment: Комментарий к изменению
            
        Returns:
            (номер новой версии, создана ли новая версия)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Получаем текущую конфигурацию
            cursor.execute("""
                SELECT c.current_version, cv.content, cv.hash
                FROM configs c
                LEFT JOIN config_versions cv ON c.id = cv.config_id AND c.current_version = cv.version
                WHERE c.id = ?
            """, (config_id,))
            
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Config '{config_id}' not found")
            
            current_version = row['current_version']
            current_content = json.loads(row['content']) if row['content'] else {}
            current_hash = row['hash']
            
            # Вычисляем хеш новой конфигурации
            new_hash = ConfigHashCalculator.calculate_hash(content)
            
            # Проверяем, изменилась ли конфигурация
            if new_hash == current_hash:
                logger.info(f"Config '{config_id}' not changed, skipping version creation")
                return current_version, False
            
            # Создаем новую версию
            new_version = current_version + 1
            
            version_id = self._create_version(
                config_id, new_version, content, created_by,
                ChangeType.UPDATED, current_version, conn
            )
            
            # Обновляем комментарий если указан
            if comment:
                cursor.execute("""
                    UPDATE config_versions 
                    SET comment = ? 
                    WHERE id = ?
                """, (comment, version_id))
            
            # Обновляем текущую версию конфигурации
            cursor.execute("""
                UPDATE configs 
                SET current_version = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (new_version, config_id))
            
            conn.commit()
            
            logger.info(f"Updated config '{config_id}' to version {new_version}")
            return new_version, True
    
    def get_config(self, config_id: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Получение конфигурации.
        
        Args:
            config_id: ID конфигурации
            version: Версия (None для текущей)
            
        Returns:
            Конфигурация или None если не найдена
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if version is None:
                # Получаем текущую версию
                cursor.execute("""
                    SELECT cv.content, cv.version, c.format
                    FROM configs c
                    JOIN config_versions cv ON c.id = cv.config_id AND c.current_version = cv.version
                    WHERE c.id = ?
                """, (config_id,))
            else:
                # Получаем конкретную версию
                cursor.execute("""
                    SELECT cv.content, cv.version, c.format
                    FROM configs c
                    JOIN config_versions cv ON c.id = cv.config_id AND cv.version = ?
                    WHERE c.id = ?
                """, (version, config_id))
            
            row = cursor.fetchone()
            if row:
                return {
                    'content': json.loads(row['content']),
                    'version': row['version'],
                    'format': ConfigFormat(row['format'])
                }
            
            return None
    
    def get_version_history(self, config_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получение истории версий конфигурации.
        
        Args:
            config_id: ID конфигурации
            limit: Максимальное количество версий
            
        Returns:
            Список версий
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    version,
                    hash,
                    created_at,
                    created_by,
                    comment,
                    change_type,
                    parent_version
                FROM config_versions 
                WHERE config_id = ? 
                ORDER BY version DESC 
                LIMIT ?
            """, (config_id, limit))
            
            versions = []
            for row in cursor.fetchall():
                versions.append({
                    'version': row['version'],
                    'hash': row['hash'],
                    'created_at': row['created_at'],
                    'created_by': row['created_by'],
                    'comment': row['comment'],
                    'change_type': ChangeType(row['change_type']),
                    'parent_version': row['parent_version']
                })
            
            return versions
    
    def get_diff(self, config_id: str, from_version: int, to_version: int) -> Optional[ConfigDiff]:
        """
        Получение различий между версиями.
        
        Args:
            config_id: ID конфигурации
            from_version: Исходная версия
            to_version: Целевая версия
            
        Returns:
            Различия или None если версии не найдены
        """
        # Получаем конфигурации
        from_config_data = self.get_config(config_id, from_version)
        to_config_data = self.get_config(config_id, to_version)
        
        if not from_config_data or not to_config_data:
            return None
        
        # Вычисляем различия
        diff = ConfigDiffCalculator.calculate_diff(
            from_config_data['content'],
            to_config_data['content']
        )
        
        diff.from_version = from_version
        diff.to_version = to_version
        
        return diff
    
    def rollback(self, config_id: str, target_version: int, created_by: str = "system") -> bool:
        """
        Откат конфигурации к предыдущей версии.
        
        Args:
            config_id: ID конфигурации
            target_version: Версия для отката
            created_by: Автор
            
        Returns:
            True если успешно
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Получаем целевую версию
            cursor.execute("""
                SELECT content FROM config_versions 
                WHERE config_id = ? AND version = ?
            """, (config_id, target_version))
            
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Version {target_version} not found for config '{config_id}'")
            
            target_content = json.loads(row['content'])
            
            # Получаем текущую версию
            cursor.execute("""
                SELECT current_version FROM configs WHERE id = ?
            """, (config_id,))
            
            current_version_row = cursor.fetchone()
            if not current_version_row:
                raise ValueError(f"Config '{config_id}' not found")
            
            current_version = current_version_row['current_version']
            
            # Создаем новую версию с типом ROLLBACK
            new_version = current_version + 1
            version_id = self._create_version(
                config_id, new_version, target_content, created_by,
                ChangeType.ROLLBACK, current_version, conn
            )
            
            # Обновляем комментарий
            cursor.execute("""
                UPDATE config_versions 
                SET comment = ? 
                WHERE id = ?
            """, (f"Rollback from version {current_version} to {target_version}", version_id))
            
            # Обновляем текущую версию
            cursor.execute("""
                UPDATE configs 
                SET current_version = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (new_version, config_id))
            
            conn.commit()
            
            logger.info(f"Rolled back config '{config_id}' from version {current_version} to {target_version}")
            return True
    
    def search_configs(
        self,
        name_filter: Optional[str] = None,
        tag_filter: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Поиск конфигураций.
        
        Args:
            name_filter: Фильтр по имени (подстрока)
            tag_filter: Фильтр по тегам
            limit: Максимальное количество результатов
            
        Returns:
            Список конфигураций
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    c.id,
                    c.name,
                    c.description,
                    c.format,
                    c.current_version,
                    c.created_at,
                    c.updated_at,
                    c.created_by,
                    c.tags,
                    cv.created_at as last_updated
                FROM configs c
                JOIN config_versions cv ON c.id = cv.config_id AND c.current_version = cv.version
                WHERE c.is_active = TRUE
            """
            
            params = []
            
            if name_filter:
                query += " AND c.name LIKE ?"
                params.append(f"%{name_filter}%")
            
            if tag_filter:
                # Поиск по тегам (теги хранятся как JSON массив)
                tag_conditions = []
                for tag in tag_filter:
                    tag_conditions.append("c.tags LIKE ?")
                    params.append(f'%"{tag}"%')
                
                query += " AND (" + " OR ".join(tag_conditions) + ")"
            
            query += " ORDER BY c.updated_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            
            configs = []
            for row in cursor.fetchall():
                configs.append({
                    'id': row['id'],
                    'name': row['name'],
                    'description': row['description'],
                    'format': ConfigFormat(row['format']),
                    'current_version': row['current_version'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at'],
                    'created_by': row['created_by'],
                    'tags': json.loads(row['tags']) if row['tags'] else [],
                    'last_updated': row['last_updated']
                })
            
            return configs


class ConfigManager:
    """Менеджер конфигураций."""
    
    def __init__(self, storage: Optional[ConfigStorage] = None):
        self.storage = storage or ConfigStorage()
        self.validator = ConfigValidator()
        self.parser = ConfigParser()
    
    def load_from_file(
        self,
        file_path: str,
        config_name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Tuple[str, int]:
        """
        Загрузка конфигурации из файла.
        
        Args:
            file_path: Путь к файлу
            config_name: Имя конфигурации (None = имя файла)
            description: Описание
            tags: Теги
            
        Returns:
            (ID конфигурации, номер версии)
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")
        
        # Определяем формат по расширению
        ext = path.suffix.lower()
        format_map = {
            '.json': ConfigFormat.JSON,
            '.yaml': ConfigFormat.YAML,
            '.yml': ConfigFormat.YAML,
            '.toml': ConfigFormat.TOML,
            '.ini': ConfigFormat.INI,
            '.cfg': ConfigFormat.INI,
            '.conf': ConfigFormat.INI
        }
        
        if ext not in format_map:
            raise ValueError(f"Unsupported config file format: {ext}")
        
        format = format_map[ext]
        
        # Читаем файл
        content = path.read_text(encoding='utf-8')
        
        # Парсим
        config_data = self.parser.parse(content, format)
        
        # Используем имя файла если не указано
        name = config_name or path.stem
        
        # Сохраняем
        return self.storage.create_config(
            name=name,
            content=config_data,
            format=format,
            description=description or f"Loaded from {file_path}",
            tags=tags
        )
    
    def validate_config(self, config_id: str, config_type: Optional[str] = None) -> Tuple[bool, List[str]]:
        """
        Валидация конфигурации.
        
        Args:
            config_id: ID конфигурации
            config_type: Тип конфигурации для выбора схемы
            
        Returns:
            (валидна, список ошибок)
        """
        config_data = self.storage.get_config(config_id)
        if not config_data:
            return False, [f"Config '{config_id}' not found"]
        
        if config_type and config_type in self.validator.schema_registry:
            schema = self.validator.schema_registry[config_type]
            return self.validator.validate(config_data['content'], schema)
        else:
            # Базовая валидация - проверяем что это валидный JSON/словарь
            if isinstance(config_data['content'], dict):
                return True, []
            else:
                return False, ["Config content must be a dictionary"]
    
    def export_config(
        self,
        config_id: str,
        version: Optional[int] = None,
        export_format: Optional[ConfigFormat] = None,
        file_path: Optional[str] = None
    ) -> str:
        """
        Экспорт конфигурации.
        
        Args:
            config_id: ID конфигурации
            version: Версия (None для текущей)
            export_format: Формат экспорта (None для родного формата)
            file_path: Путь для сохранения файла
            
        Returns:
            Экспортированная строка
        """
        config_data = self.storage.get_config(config_id, version)
        if not config_data:
            raise ValueError(f"Config '{config_id}' not found")
        
        # Определяем формат экспорта
        format = export_format or config_data['format']
        
        # Сериализуем
        exported = self.parser.serialize(config_data['content'], format)
        
        # Сохраняем в файл если указан путь
        if file_path:
            Path(file_path).write_text(exported, encoding='utf-8')
            logger.info(f"Exported config '{config_id}' to {file_path}")
        
        return exported
    
    def get_audit_log(
        self,
        config_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        created_by: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Получение аудит-лога изменений.
        
        Args:
            config_id: ID конфигурации (None для всех)
            start_date: Начало периода
            end_date: Конец периода
            created_by: Автор изменений
            limit: Максимальное количество записей
            
        Returns:
            Список записей аудит-лога
        """
        with self.storage._get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    cv.config_id,
                    c.name as config_name,
                    cv.version,
                    cv.change_type,
                    cv.created_at,
                    cv.created_by,
                    cv.comment,
                    cv.parent_version
                FROM config_versions cv
                JOIN configs c ON cv.config_id = c.id
                WHERE 1=1
            """
            
            params = []
            
            if config_id:
                query += " AND cv.config_id = ?"
                params.append(config_id)
            
            if start_date:
                query += " AND cv.created_at >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND cv.created_at <= ?"
                params.append(end_date)
            
            if created_by:
                query += " AND cv.created_by = ?"
                params.append(created_by)
            
            query += " ORDER BY cv.created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            
            audit_log = []
            for row in cursor.fetchall():
                audit_log.append({
                    'config_id': row['config_id'],
                    'config_name': row['config_name'],
                    'version': row['version'],
                    'change_type': ChangeType(row['change_type']),
                    'created_at': row['created_at'],
                    'created_by': row['created_by'],
                    'comment': row['comment'],
                    'parent_version': row['parent_version']
                })
            
            return audit_log


# --- Пример использования ---
def main():
    """Демонстрация работы системы управления версиями конфигураций."""
    print("=== Configuration Version Management System Demo ===")
    
    # Создаем менеджер конфигураций
    manager = ConfigManager()
    
    try:
        # Регистрируем схемы валидации
        print("\n1. Registering validation schemas...")
        
        app_schema = {
            "type": "object",
            "properties": {
                "app_name": {"type": "string"},
                "version": {"type": "string"},
                "debug": {"type": "boolean"},
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "database": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string"},
                        "port": {"type": "integer"},
                        "name": {"type": "string"}
                    },
                    "required": ["host", "name"]
                }
            },
            "required": ["app_name", "port"]
        }
        
        manager.validator.register_schema("application", app_schema)
        
        # Загружаем конфигурацию из файла (или создаем тестовую)
        print("\n2. Creating initial configuration...")
        
        test_config = {
            "app_name": "My Application",
            "version": "1.0.0",
            "debug": True,
            "port": 8080,
            "database": {
                "host": "localhost",
                "port": 5432,
                "name": "mydb"
            },
            "features": {
                "auth": True,
                "cache": False,
                "logging": {
                    "level": "INFO",
                    "file": "/var/log/app.log"
                }
            }
        }
        
        config_id, version = manager.storage.create_config(
            name="app_config",
            content=test_config,
            format=ConfigFormat.JSON,
            description="Main application configuration",
            tags=["application", "production", "backend"]
        )
        
        print(f"Created config: {config_id}, version: {version}")
        
        # Валидируем конфигурацию
        print("\n3. Validating configuration...")
        is_valid, errors = manager.validate_config(config_id, "application")
        
        if is_valid:
            print("✓ Configuration is valid")
        else:
            print("✗ Configuration validation errors:")
            for error in errors:
                print(f"  - {error}")
        
        # Обновляем конфигурацию
        print("\n4. Updating configuration...")
        
        updated_config = test_config.copy()
        updated_config["port"] = 9000
        updated_config["database"]["host"] = "db.example.com"
        updated_config["features"]["cache"] = True
        
        new_version, changed = manager.storage.update_config(
            config_id=config_id,
            content=updated_config,
            created_by="admin",
            comment="Updated port and database host"
        )
        
        print(f"New version: {new_version}, changed: {changed}")
        
        # Получаем историю версий
        print("\n5. Version history:")
        history = manager.storage.get_version_history(config_id)
        
        for item in history:
            print(f"  Version {item['version']}: {item['change_type'].value} by {item['created_by']}")
            if item['comment']:
                print(f"    Comment: {item['comment']}")
        
        # Сравниваем версии
        print("\n6. Comparing versions 1 and 2...")
        diff = manager.storage.get_diff(config_id, 1, 2)
        
        if diff:
            print(f"  Added keys: {len(diff.added_keys)}")
            print(f"  Removed keys: {len(diff.removed_keys)}")
            print(f"  Modified keys: {len(diff.modified_keys)}")
            
            if diff.modified_keys:
                print("  Modified keys:")
                for key in diff.modified_keys[:3]:  # Показываем первые 3
                    print(f"    - {key}")
        
        # Экспортируем конфигурацию
        print("\n7. Exporting configuration...")
        exported = manager.export_config(config_id, version=2)
        print(f"Exported config (first 200 chars): {exported[:200]}...")
        
        # Создаем еще одну конфигурацию
        print("\n8. Creating another configuration...")
        
        another_config = {
            "service_name": "auth_service",
            "jwt_secret": "supersecret",
            "token_expiry": 3600
        }
        
        config_id2, _ = manager.storage.create_config(
            name="auth_config",
            content=another_config,
            format=ConfigFormat.JSON,
            tags=["authentication", "security", "backend"]
        )
        
        # Ищем конфигурации
        print("\n9. Searching configurations...")
        results = manager.storage.search_configs(
            name_filter="config",
            tag_filter=["backend"],
            limit=5
        )
        
        print(f"Found {len(results)} configurations:")
        for config in results:
            print(f"  - {config['name']} (v{config['current_version']}), tags: {config['tags']}")
        
        # Получаем аудит-лог
        print("\n10. Audit log:")
        audit_log = manager.get_audit_log(limit=5)
        
        for entry in audit_log:
            print(f"  {entry['config_name']} v{entry['version']}: "
                  f"{entry['change_type'].value} by {entry['created_by']}")
        
        # Откат конфигурации
        print("\n11. Rolling back to version 1...")
        success = manager.storage.rollback(config_id, target_version=1, created_by="admin")
        
        if success:
            print("✓ Rollback successful")
            
            # Проверяем текущую версию
            current_config = manager.storage.get_config(config_id)
            print(f"Current version after rollback: {current_config['version']}")
        
        # Очистка (в реальном приложении - по расписанию)
        print("\n12. Demo completed!")
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()