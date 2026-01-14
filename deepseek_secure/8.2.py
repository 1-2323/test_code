import json
import yaml
import tomllib
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Type, TypeVar, Dict, Union, Optional
from pathlib import Path
import warnings

T = TypeVar('T', bound='DataDeserializer')


class DeserializationError(Exception):
    """Исключение при ошибке десериализации"""
    pass


class UnsupportedFormatError(DeserializationError):
    """Исключение при неподдерживаемом формате"""
    pass


class DeserializationWarning(Warning):
    """Предупреждение при десериализации"""
    pass


class DataFormat(Enum):
    """Поддерживаемые форматы данных"""
    JSON = 'json'
    YAML = 'yaml'
    TOML = 'toml'
    XML = 'xml'
    # Pickle исключен из соображений безопасности (CWE-502)


class DataDeserializer(ABC):
    """Абстрактный базовый класс для десериализации данных"""
    
    def __init__(self, strict_mode: bool = True):
        """
        Инициализация десериализатора
        
        Args:
            strict_mode: Строгий режим проверки данных
        """
        self.strict_mode = strict_mode
        self._validation_schema = None
    
    @abstractmethod
    def deserialize(self, data: Union[str, bytes, Path], 
                   target_class: Optional[Type] = None) -> Any:
        """
        Десериализация данных
        
        Args:
            data: Данные для десериализации
            target_class: Целевой класс для преобразования
            
        Returns:
            Десериализованный объект
            
        Raises:
            DeserializationError: Ошибка десериализации
        """
        pass
    
    def set_validation_schema(self, schema: Dict[str, Any]) -> None:
        """
        Установка схемы валидации данных
        
        Args:
            schema: Схема валидации
        """
        self._validation_schema = schema
    
    def _validate_data(self, data: Any) -> bool:
        """
        Валидация данных по схеме
        
        Args:
            data: Данные для валидации
            
        Returns:
            Результат валидации
        """
        if not self._validation_schema:
            return True
        
        # Базовая реализация валидации
        # В реальном проекте здесь можно использовать jsonschema или подобную библиотеку
        try:
            return self._perform_validation(data, self._validation_schema)
        except Exception as e:
            if self.strict_mode:
                raise DeserializationError(f"Validation failed: {str(e)}")
            warnings.warn(f"Validation warning: {str(e)}", DeserializationWarning)
            return False
    
    def _perform_validation(self, data: Any, schema: Dict[str, Any]) -> bool:
        """
        Выполнение валидации данных
        
        Args:
            data: Данные для валидации
            schema: Схема валидации
            
        Returns:
            Результат валидации
        """
        # Заглушка для реализации валидации
        # В реальном проекте здесь должна быть полноценная логика валидации
        return True
    
    def _convert_to_target_class(self, data: Dict[str, Any], 
                                target_class: Type) -> Any:
        """
        Преобразование словаря в целевой класс
        
        Args:
            data: Данные в виде словаря
            target_class: Целевой класс
            
        Returns:
            Экземпляр целевого класса
        """
        try:
            if hasattr(target_class, 'from_dict'):
                return target_class.from_dict(data)
            else:
                return target_class(**data)
        except (TypeError, ValueError) as e:
            raise DeserializationError(
                f"Failed to convert to {target_class.__name__}: {str(e)}"
            )
    
    @classmethod
    def create_deserializer(cls: Type[T], 
                           data_format: Union[DataFormat, str],
                           **kwargs) -> T:
        """
        Фабричный метод для создания десериализатора
        
        Args:
            data_format: Формат данных
            **kwargs: Дополнительные параметры
            
        Returns:
            Экземпляр десериализатора
            
        Raises:
            UnsupportedFormatError: Неподдерживаемый формат
        """
        if isinstance(data_format, str):
            try:
                data_format = DataFormat(data_format.lower())
            except ValueError:
                raise UnsupportedFormatError(
                    f"Unsupported format: {data_format}. "
                    f"Supported formats: {[f.value for f in DataFormat]}"
                )
        
        if data_format == DataFormat.JSON:
            return JSONDeserializer(**kwargs)
        elif data_format == DataFormat.YAML:
            return YAMLDeserializer(**kwargs)
        elif data_format == DataFormat.TOML:
            return TOMLDeserializer(**kwargs)
        elif data_format == DataFormat.XML:
            return XMLDeserializer(**kwargs)
        else:
            raise UnsupportedFormatError(
                f"Unsupported format: {data_format}. "
                f"Pickle is excluded for security reasons (CWE-502)."
            )


class JSONDeserializer(DataDeserializer):
    """Десериализатор JSON"""
    
    def deserialize(self, data: Union[str, bytes, Path],
                   target_class: Optional[Type] = None) -> Any:
        try:
            # Чтение из файла, если передан путь
            if isinstance(data, Path):
                if not data.exists():
                    raise DeserializationError(f"File not found: {data}")
                with open(data, 'r', encoding='utf-8') as f:
                    data = f.read()
            
            # Десериализация JSON
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            
            result = json.loads(data)
            
            # Валидация данных
            if not self._validate_data(result):
                if self.strict_mode:
                    raise DeserializationError("Data validation failed")
            
            # Преобразование в целевой класс, если указан
            if target_class and isinstance(result, dict):
                return self._convert_to_target_class(result, target_class)
            
            return result
            
        except json.JSONDecodeError as e:
            raise DeserializationError(f"JSON decode error: {str(e)}")
        except Exception as e:
            raise DeserializationError(f"JSON deserialization error: {str(e)}")


class YAMLDeserializer(DataDeserializer):
    """Десериализатор YAML"""
    
    def __init__(self, strict_mode: bool = True, safe_load: bool = True):
        """
        Инициализация YAML десериализатора
        
        Args:
            strict_mode: Строгий режим проверки данных
            safe_load: Безопасная загрузка (рекомендуется)
        """
        super().__init__(strict_mode)
        self.safe_load = safe_load
        
        if not safe_load:
            warnings.warn(
                "Using unsafe YAML loading is not recommended",
                DeserializationWarning
            )
    
    def deserialize(self, data: Union[str, bytes, Path],
                   target_class: Optional[Type] = None) -> Any:
        try:
            # Чтение из файла, если передан путь
            if isinstance(data, Path):
                if not data.exists():
                    raise DeserializationError(f"File not found: {data}")
                with open(data, 'r', encoding='utf-8') as f:
                    data = f.read()
            
            # Десериализация YAML
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            
            if self.safe_load:
                result = yaml.safe_load(data)
            else:
                result = yaml.load(data, Loader=yaml.Loader)
            
            # Валидация данных
            if not self._validate_data(result):
                if self.strict_mode:
                    raise DeserializationError("Data validation failed")
            
            # Преобразование в целевой класс, если указан
            if target_class and isinstance(result, dict):
                return self._convert_to_target_class(result, target_class)
            
            return result
            
        except yaml.YAMLError as e:
            raise DeserializationError(f"YAML parse error: {str(e)}")
        except Exception as e:
            raise DeserializationError(f"YAML deserialization error: {str(e)}")


class TOMLDeserializer(DataDeserializer):
    """Десериализатор TOML"""
    
    def deserialize(self, data: Union[str, bytes, Path],
                   target_class: Optional[Type] = None) -> Any:
        try:
            # Чтение из файла, если передан путь
            if isinstance(data, Path):
                if not data.exists():
                    raise DeserializationError(f"File not found: {data}")
                with open(data, 'rb') as f:
                    result = tomllib.load(f)
            else:
                # Десериализация TOML из строки/байтов
                if isinstance(data, str):
                    data = data.encode('utf-8')
                result = tomllib.loads(data)
            
            # Валидация данных
            if not self._validate_data(result):
                if self.strict_mode:
                    raise DeserializationError("Data validation failed")
            
            # Преобразование в целевой класс, если указан
            if target_class and isinstance(result, dict):
                return self._convert_to_target_class(result, target_class)
            
            return result
            
        except tomllib.TOMLDecodeError as e:
            raise DeserializationError(f"TOML decode error: {str(e)}")
        except Exception as e:
            raise DeserializationError(f"TOML deserialization error: {str(e)}")


class XMLDeserializer(DataDeserializer):
    """Десериализатор XML"""
    
    def __init__(self, strict_mode: bool = True, 
                 custom_parser: Optional[ET.XMLParser] = None):
        """
        Инициализация XML десериализатора
        
        Args:
            strict_mode: Строгий режим проверки данных
            custom_parser: Кастомный XML парсер
        """
        super().__init__(strict_mode)
        self.parser = custom_parser or ET.XMLParser(
            encoding='utf-8',
            forbid_dtd=True,  # Запрещаем DTD для безопасности
            forbid_entities=True  # Запрещаем внешние entity
        )
    
    def deserialize(self, data: Union[str, bytes, Path],
                   target_class: Optional[Type] = None) -> Any:
        try:
            # Чтение из файла, если передан путь
            if isinstance(data, Path):
                if not data.exists():
                    raise DeserializationError(f"File not found: {data}")
                tree = ET.parse(data, parser=self.parser)
                root = tree.getroot()
            else:
                # Десериализация XML из строки/байтов
                if isinstance(data, bytes):
                    data = data.decode('utf-8')
                root = ET.fromstring(data, parser=self.parser)
            
            # Преобразование XML в словарь
            result = self._xml_to_dict(root)
            
            # Валидация данных
            if not self._validate_data(result):
                if self.strict_mode:
                    raise DeserializationError("Data validation failed")
            
            # Преобразование в целевой класс, если указан
            if target_class and isinstance(result, dict):
                return self._convert_to_target_class(result, target_class)
            
            return result
            
        except ET.ParseError as e:
            raise DeserializationError(f"XML parse error: {str(e)}")
        except Exception as e:
            raise DeserializationError(f"XML deserialization error: {str(e)}")
    
    def _xml_to_dict(self, element: ET.Element) -> Dict[str, Any]:
        """Рекурсивное преобразование XML элемента в словарь"""
        result = {}
        
        # Обработка атрибутов
        if element.attrib:
            result['@attributes'] = element.attrib
        
        # Обработка дочерних элементов
        children = {}
        for child in element:
            child_dict = self._xml_to_dict(child)
            
            if child.tag in children:
                if not isinstance(children[child.tag], list):
                    children[child.tag] = [children[child.tag]]
                children[child.tag].append(child_dict)
            else:
                children[child.tag] = child_dict
        
        if children:
            result.update(children)
        
        # Обработка текста
        if element.text and element.text.strip():
            if result:  # Если есть атрибуты или дети
                result['#text'] = element.text.strip()
            else:  # Если только текст
                return element.text.strip()
        
        return result