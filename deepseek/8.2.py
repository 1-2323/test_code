import json
import pickle
import yaml
import csv
import io
import base64
from abc import ABC, abstractmethod
from typing import Any, Dict, Type, TypeVar, Generic, Optional, Union
from dataclasses import is_dataclass, asdict
from enum import Enum
import warnings

T = TypeVar('T')


class DeserializationError(Exception):
    """Исключение при ошибке десериализации"""
    pass


class BaseDeserializer(ABC, Generic[T]):
    """Базовый класс десериализатора"""
    
    @abstractmethod
    def deserialize(self, data: Any, target_type: Optional[Type[T]] = None) -> T:
        """Десериализация данных"""
        pass


class JsonDeserializer(BaseDeserializer[T]):
    """Десериализатор JSON"""
    
    def __init__(self, 
                 encoding: str = 'utf-8',
                 strict: bool = True,
                 object_hook: Optional[callable] = None):
        self.encoding = encoding
        self.strict = strict
        self.object_hook = object_hook
    
    def deserialize(self, 
                    data: Union[str, bytes, bytearray], 
                    target_type: Optional[Type[T]] = None) -> T:
        """
        Десериализация JSON данных
        
        Args:
            data: JSON строка или байты
            target_type: Ожидаемый тип результата (опционально)
            
        Returns:
            Десериализованный объект
        """
        try:
            if isinstance(data, (bytes, bytearray)):
                data = data.decode(self.encoding)
            
            kwargs = {}
            if self.object_hook:
                kwargs['object_hook'] = self.object_hook
            
            result = json.loads(data, strict=self.strict, **kwargs)
            
            if target_type:
                result = self._convert_to_type(result, target_type)
            
            return result
            
        except json.JSONDecodeError as e:
            raise DeserializationError(f"Invalid JSON: {str(e)}")
        except (UnicodeDecodeError, TypeError) as e:
            raise DeserializationError(f"Data decoding error: {str(e)}")
    
    def _convert_to_type(self, data: Any, target_type: Type[T]) -> T:
        """Конвертация данных в указанный тип"""
        try:
            if is_dataclass(target_type):
                return self._deserialize_dataclass(data, target_type)
            elif hasattr(target_type, '__annotations__'):
                return self._deserialize_typed_dict(data, target_type)
            elif issubclass(target_type, dict):
                return target_type(data)
            elif issubclass(target_type, list):
                return target_type(data)
            elif issubclass(target_type, (str, int, float, bool)):
                return target_type(data)
            elif issubclass(target_type, Enum):
                return self._deserialize_enum(data, target_type)
            else:
                return target_type(**data) if isinstance(data, dict) else target_type(data)
        except Exception as e:
            raise DeserializationError(f"Type conversion error: {str(e)}")
    
    def _deserialize_dataclass(self, data: Dict, target_type: Type[T]) -> T:
        """Десериализация в dataclass"""
        if not isinstance(data, dict):
            raise DeserializationError(f"Expected dict for dataclass, got {type(data).__name__}")
        
        init_kwargs = {}
        for field_name, field_type in target_type.__annotations__.items():
            if field_name in data:
                init_kwargs[field_name] = self._convert_field(data[field_name], field_type)
        
        return target_type(**init_kwargs)
    
    def _deserialize_typed_dict(self, data: Dict, target_type: Type[T]) -> T:
        """Десериализация в TypedDict или класс с аннотациями"""
        if not isinstance(data, dict):
            raise DeserializationError(f"Expected dict for typed class, got {type(data).__name__}")
        
        result = target_type() if callable(target_type) else {}
        
        for field_name, field_type in target_type.__annotations__.items():
            if field_name in data:
                if hasattr(result, '__setitem__'):
                    result[field_name] = self._convert_field(data[field_name], field_type)
                else:
                    setattr(result, field_name, self._convert_field(data[field_name], field_type))
        
        return result
    
    def _deserialize_enum(self, data: Any, target_type: Type[Enum]) -> Enum:
        """Десериализация Enum"""
        if isinstance(data, str):
            return target_type[data]
        elif isinstance(data, int):
            return target_type(data)
        else:
            return target_type(data)
    
    def _convert_field(self, value: Any, field_type: Any) -> Any:
        """Конвертация отдельного поля"""
        # Упрощенная обработка типов (в реальном проекте можно использовать pydantic или подобное)
        origin = getattr(field_type, '__origin__', None)
        args = getattr(field_type, '__args__', None)
        
        if origin is list and args:
            return [self._convert_field(item, args[0]) for item in value]
        elif origin is dict and args and len(args) == 2:
            return {self._convert_field(k, args[0]): self._convert_field(v, args[1]) 
                    for k, v in value.items()}
        elif origin is Union:
            for arg in args:
                try:
                    return self._convert_field(value, arg)
                except:
                    continue
            return value
        else:
            return value


class PickleDeserializer(BaseDeserializer[T]):
    """Десериализатор pickle"""
    
    def __init__(self, 
                 protocol: Optional[int] = None,
                 fix_imports: bool = True,
                 encoding: str = 'ASCII',
                 errors: str = 'strict',
                 safe: bool = True):
        self.protocol = protocol
        self.fix_imports = fix_imports
        self.encoding = encoding
        self.errors = errors
        self.safe = safe
        
        if safe:
            warnings.warn(
                "Safe mode restricts unpickling. Use only with trusted data.",
                UserWarning
            )
    
    def deserialize(self, 
                    data: Union[bytes, bytearray], 
                    target_type: Optional[Type[T]] = None) -> T:
        """
        Десериализация pickle данных
        
        Args:
            data: Бинарные данные pickle
            target_type: Ожидаемый тип результата (опционально, для валидации)
            
        Returns:
            Десериализованный объект
        """
        if not isinstance(data, (bytes, bytearray)):
            raise DeserializationError(f"Expected bytes for pickle, got {type(data).__name__}")
        
        try:
            if self.safe:
                result = self._safe_loads(data)
            else:
                result = pickle.loads(
                    data, 
                    fix_imports=self.fix_imports,
                    encoding=self.encoding,
                    errors=self.errors
                )
            
            if target_type and not isinstance(result, target_type):
                raise DeserializationError(
                    f"Deserialized object type {type(result).__name__} "
                    f"does not match expected type {target_type.__name__}"
                )
            
            return result
            
        except pickle.UnpicklingError as e:
            raise DeserializationError(f"Pickle unpickling error: {str(e)}")
        except Exception as e:
            raise DeserializationError(f"Pickle deserialization error: {str(e)}")
    
    def _safe_loads(self, data: bytes) -> Any:
        """Безопасная десериализация с ограничениями"""
        # Создаем кастомный Unpickler с белым списком разрешенных классов
        class RestrictedUnpickler(pickle.Unpickler):
            ALLOWED_CLASSES = {
                'builtins': {'set', 'frozenset', 'tuple', 'list', 'dict', 'int', 'float', 
                            'str', 'bool', 'bytes', 'bytearray', 'type', 'NoneType'},
                'collections': {'OrderedDict', 'defaultdict', 'deque'},
                'datetime': {'datetime', 'date', 'time'},
                'decimal': {'Decimal'},
                'uuid': {'UUID'},
            }
            
            def find_class(self, module, name):
                # Разрешаем только безопасные классы
                if module in self.ALLOWED_CLASSES and name in self.ALLOWED_CLASSES[module]:
                    return super().find_class(module, name)
                if module == '__main__':
                    raise pickle.UnpicklingError(f"Access to __main__.{name} is restricted")
                raise pickle.UnpicklingError(f"Global '{module}.{name}' is forbidden")
        
        stream = io.BytesIO(data)
        unpickler = RestrictedUnpickler(stream)
        return unpickler.load()


class YamlDeserializer(BaseDeserializer[T]):
    """Десериализатор YAML"""
    
    def __init__(self, 
                 loader_type: str = 'safe',
                 encoding: str = 'utf-8'):
        self.loader_type = loader_type
        self.encoding = encoding
        
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required for YAML deserialization")
    
    def deserialize(self, 
                    data: Union[str, bytes], 
                    target_type: Optional[Type[T]] = None) -> T:
        """Десериализация YAML данных"""
        try:
            if isinstance(data, bytes):
                data = data.decode(self.encoding)
            
            if self.loader_type == 'safe':
                result = yaml.safe_load(data)
            elif self.loader_type == 'full':
                result = yaml.full_load(data)
            else:
                result = yaml.load(data, Loader=yaml.Loader)
            
            if target_type:
                # Простая конвертация типов для YAML
                result = self._convert_yaml_to_type(result, target_type)
            
            return result
            
        except yaml.YAMLError as e:
            raise DeserializationError(f"YAML parsing error: {str(e)}")
        except Exception as e:
            raise DeserializationError(f"YAML deserialization error: {str(e)}")
    
    def _convert_yaml_to_type(self, data: Any, target_type: Type[T]) -> T:
        """Конвертация YAML данных в указанный тип"""
        # Базовая реализация, можно расширить
        if isinstance(data, dict) and hasattr(target_type, '__annotations__'):
            return target_type(**data)
        return data


class DataRestorer:
    """Основной класс для восстановления данных из различных форматов"""
    
    def __init__(self):
        self._deserializers = {
            'json': JsonDeserializer(),
            'pickle': PickleDeserializer(safe=True),
            'yaml': YamlDeserializer(),
        }
        self._format_detectors = [
            (self._is_json, 'json'),
            (self._is_pickle, 'pickle'),
            (self._is_yaml, 'yaml'),
        ]
    
    def register_deserializer(self, format_name: str, deserializer: BaseDeserializer):
        """Регистрация кастомного десериализатора"""
        self._deserializers[format_name] = deserializer
    
    def restore(self, 
                data: Any, 
                format_name: Optional[str] = None,
                target_type: Optional[Type[T]] = None) -> T:
        """
        Восстановление данных из различных форматов
        
        Args:
            data: Данные для десериализации
            format_name: Имя формата (json, pickle, yaml) или None для автоопределения
            target_type: Ожидаемый тип результата
            
        Returns:
            Восстановленный объект
        """
        if format_name is None:
            format_name = self._detect_format(data)
        
        if format_name not in self._deserializers:
            raise DeserializationError(f"Unsupported format: {format_name}")
        
        deserializer = self._deserializers[format_name]
        return deserializer.deserialize(data, target_type)
    
    def restore_from_file(self, 
                          filepath: str, 
                          format_name: Optional[str] = None,
                          target_type: Optional[Type[T]] = None) -> T:
        """Восстановление данных из файла"""
        import os
        
        if not os.path.exists(filepath):
            raise DeserializationError(f"File not found: {filepath}")
        
        if format_name is None:
            format_name = self._detect_format_from_extension(filepath)
        
        with open(filepath, 'rb') as f:
            data = f.read()
        
        return self.restore(data, format_name, target_type)
    
    def restore_from_base64(self, 
                           encoded_data: str, 
                           format_name: str,
                           target_type: Optional[Type[T]] = None) -> T:
        """Восстановление данных из base64 строки"""
        try:
            data = base64.b64decode(encoded_data)
            return self.restore(data, format_name, target_type)
        except base64.binascii.Error as e:
            raise DeserializationError(f"Base64 decoding error: {str(e)}")
    
    def _detect_format(self, data: Any) -> str:
        """Автоопределение формата данных"""
        for detector, format_name in self._format_detectors:
            if detector(data):
                return format_name
        
        raise DeserializationError("Unable to detect data format")
    
    def _detect_format_from_extension(self, filepath: str) -> str:
        """Определение формата по расширению файла"""
        import os
        ext = os.path.splitext(filepath)[1].lower()
        
        extension_map = {
            '.json': 'json',
            '.pkl': 'pickle',
            '.pickle': 'pickle',
            '.yaml': 'yaml',
            '.yml': 'yaml',
        }
        
        if ext in extension_map:
            return extension_map[ext]
        
        raise DeserializationError(f"Unable to detect format from extension: {ext}")
    
    def _is_json(self, data: Any) -> bool:
        """Проверка, является ли data JSON"""
        if isinstance(data, (str, bytes, bytearray)):
            try:
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode('utf-8', errors='ignore')
                data = data.strip()
                return (data.startswith('{') and data.endswith('}')) or \
                       (data.startswith('[') and data.endswith(']'))
            except:
                pass
        return False
    
    def _is_pickle(self, data: Any) -> bool:
        """Проверка, является ли data pickle"""
        if isinstance(data, (bytes, bytearray)):
            # Проверка на сигнатуру pickle
            if len(data) >= 2:
                # Проверка PROTOCOL
                if data[0] in range(0, 6):
                    # Проверка на некоторые маркеры pickle
                    markers = {b'(', b'.', b'S', b'V', b'I', b'F', b'N'}
                    if data[1:2] in markers:
                        return True
        return False
    
    def _is_yaml(self, data: Any) -> bool:
        """Проверка, является ли data YAML"""
        if isinstance(data, (str, bytes, bytearray)):
            try:
                if isinstance(data, bytes):
                    data = data.decode('utf-8', errors='ignore')
                data = data.strip()
                # Проверка на основные маркеры YAML
                return data.startswith('---') or '\n---\n' in data or ': ' in data.split('\n')[0]
            except:
                pass
        return False


# Пример использования декораторов для десериализации
def deserializable(source_format: str = 'json'):
    """Декоратор для автоматической десериализации методов"""
    def decorator(method):
        def wrapper(self, data: Any, *args, **kwargs):
            if not isinstance(data, (str, dict, list, int, float, bool)):
                restorer = DataRestorer()
                data = restorer.restore(data, source_format)
            return method(self, data, *args, **kwargs)
        return wrapper
    return decorator