from flask import Flask, request, jsonify
from functools import wraps
import json
import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import yaml
import hmac
import base64

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Блокировка для атомарных операций с конфигурацией
_config_lock = threading.RLock()
_config_version = 0
_last_update_time = None
_update_history = []


class UpdateStatus(Enum):
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"
    VALIDATED = "validated"
    REJECTED = "rejected"


class ConfigFormat(Enum):
    JSON = "json"
    YAML = "yaml"
    XML = "xml"
    PROPERTIES = "properties"


@dataclass
class ConfigSection:
    """Секция конфигурации"""
    name: str
    settings: Dict[str, Any]
    version: int = 1
    description: Optional[str] = None
    depends_on: List[str] = None
    
    def __post_init__(self):
        if self.depends_on is None:
            self.depends_on = []


@dataclass
class UpdateRequest:
    """Запрос на обновление конфигурации"""
    config_data: Dict[str, Any]
    format: ConfigFormat
    source: str
    checksum: Optional[str] = None
    timestamp: Optional[str] = None
    dry_run: bool = False
    validation_only: bool = False
    priority: int = 1


@dataclass
class UpdateResult:
    """Результат обновления"""
    request_id: str
    status: UpdateStatus
    applied_changes: Dict[str, Any]
    errors: List[str]
    warnings: List[str]
    timestamp: datetime
    duration_ms: int
    config_version: int
    rollback_available: bool = False
    rollback_reason: Optional[str] = None


class ConfigValidator:
    """Валидатор конфигурации"""
    
    def __init__(self):
        self._validators: Dict[str, Callable[[Any], bool]] = {}
        self._schema_registry: Dict[str, Dict] = {}
        self._register_default_validators()
    
    def _register_default_validators(self):
        """Регистрация стандартных валидаторов"""
        self.register_validator('required', lambda x: x is not None and x != "")
        self.register_validator('string', lambda x: isinstance(x, str))
        self.register_validator('integer', lambda x: isinstance(x, int))
        self.register_validator('boolean', lambda x: isinstance(x, bool))
        self.register_validator('positive', lambda x: isinstance(x, (int, float)) and x > 0)
        self.register_validator('list', lambda x: isinstance(x, list))
        self.register_validator('dict', lambda x: isinstance(x, dict))
    
    def register_validator(self, name: str, validator: Callable[[Any], bool]):
        """Регистрация кастомного валидатора"""
        self._validators[name] = validator
    
    def register_schema(self, schema_name: str, schema: Dict):
        """Регистрация JSON схемы"""
        self._schema_registry[schema_name] = schema
    
    def validate(self, config: Dict[str, Any], schema_name: Optional[str] = None) -> List[str]:
        """
        Валидация конфигурации
        
        Returns:
            Список ошибок валидации (пустой если все ок)
        """
        errors = []
        
        if schema_name and schema_name in self._schema_registry:
            errors.extend(self._validate_with_schema(config, schema_name))
        else:
            errors.extend(self._basic_validation(config))
        
        return errors
    
    def _basic_validation(self, config: Dict[str, Any]) -> List[str]:
        """Базовая валидация конфигурации"""
        errors = []
        
        # Проверка обязательных полей
        required_fields = ['version', 'timestamp', 'environment']
        for field in required_fields:
            if field not in config:
                errors.append(f"Missing required field: {field}")
        
        # Проверка версии конфигурации
        if 'version' in config:
            version = config['version']
            if not isinstance(version, (int, str)):
                errors.append("Config version must be integer or string")
        
        # Проверка окружения
        if 'environment' in config:
            env = config['environment']
            valid_envs = ['development', 'staging', 'production', 'test']
            if env not in valid_envs:
                errors.append(f"Invalid environment: {env}. Must be one of {valid_envs}")
        
        return errors
    
    def _validate_with_schema(self, config: Dict[str, Any], schema_name: str) -> List[str]:
        """Валидация с использованием JSON схемы"""
        # Упрощенная реализация валидации схемы
        # В реальном проекте можно использовать jsonschema
        schema = self._schema_registry[schema_name]
        errors = []
        
        for field, rules in schema.get('properties', {}).items():
            if 'required' in rules and rules['required'] and field not in config:
                errors.append(f"Required field missing: {field}")
            
            if field in config:
                value = config[field]
                
                # Проверка типа
                if 'type' in rules:
                    type_name = rules['type']
                    validator = self._validators.get(type_name)
                    if validator and not validator(value):
                        errors.append(f"Field '{field}' must be {type_name}")
                
                # Проверка минимального/максимального значения
                if isinstance(value, (int, float)):
                    if 'minimum' in rules and value < rules['minimum']:
                        errors.append(f"Field '{field}' must be >= {rules['minimum']}")
                    if 'maximum' in rules and value > rules['maximum']:
                        errors.append(f"Field '{field}' must be <= {rules['maximum']}")
                
                # Проверка длины строки
                if isinstance(value, str):
                    if 'minLength' in rules and len(value) < rules['minLength']:
                        errors.append(f"Field '{field}' must be at least {rules['minLength']} characters")
                    if 'maxLength' in rules and len(value) > rules['maxLength']:
                        errors.append(f"Field '{field}' must be at most {rules['maxLength']} characters")
                
                # Проверка по регулярному выражению
                if isinstance(value, str) and 'pattern' in rules:
                    import re
                    if not re.match(rules['pattern'], value):
                        errors.append(f"Field '{field}' does not match pattern {rules['pattern']}")
        
        return errors


class ConfigManager:
    """Менеджер конфигурации"""
    
    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._config_history: List[Dict] = []
        self._observers: List[Callable[[Dict], None]] = []
        self._validator = ConfigValidator()
        self._backup_enabled = True
        self._max_history_size = 50
    
    def get_config(self, section: Optional[str] = None) -> Dict[str, Any]:
        """Получение текущей конфигурации"""
        with _config_lock:
            if section:
                return self._config.get(section, {})
            return self._config.copy()
    
    def apply_update(self, update_request: UpdateRequest) -> UpdateResult:
        """
        Применение обновления конфигурации
        
        Args:
            update_request: Запрос на обновление
            
        Returns:
            Результат обновления
        """
        request_id = hashlib.md5(
            f"{datetime.now().isoformat()}{update_request.source}".encode()
        ).hexdigest()[:12]
        
        start_time = time.time()
        result = UpdateResult(
            request_id=request_id,
            status=UpdateStatus.PENDING,
            applied_changes={},
            errors=[],
            warnings=[],
            timestamp=datetime.now(),
            duration_ms=0,
            config_version=_config_version
        )
        
        try:
            # 1. Проверка подписи/checksum
            if update_request.checksum:
                if not self._verify_checksum(update_request):
                    result.errors.append("Checksum verification failed")
                    result.status = UpdateStatus.REJECTED
                    return result
            
            # 2. Валидация конфигурации
            validation_errors = self._validator.validate(update_request.config_data)
            if validation_errors:
                result.errors.extend(validation_errors)
                result.status = UpdateStatus.REJECTED
                return result
            
            # 3. Если это только валидация - возвращаем результат
            if update_request.validation_only:
                result.status = UpdateStatus.VALIDATED
                result.duration_ms = int((time.time() - start_time) * 1000)
                return result
            
            # 4. Dry-run режим
            if update_request.dry_run:
                result.applied_changes = self._calculate_changes(update_request.config_data)
                result.status = UpdateStatus.VALIDATED
                result.duration_ms = int((time.time() - start_time) * 1000)
                return result
            
            # 5. Применение обновления
            with _config_lock:
                # Создание backup
                if self._backup_enabled:
                    self._create_backup()
                
                # Применение изменений
                applied_changes = self._apply_config_changes(update_request.config_data)
                
                # Обновление версии
                global _config_version, _last_update_time
                _config_version += 1
                _last_update_time = datetime.now()
                
                # Сохранение в историю
                self._save_to_history(update_request, request_id)
                
                result.applied_changes = applied_changes
                result.config_version = _config_version
                result.status = UpdateStatus.APPLIED
                result.rollback_available = True
            
            # 6. Уведомление наблюдателей
            self._notify_observers(applied_changes)
            
            logger.info(f"Config updated successfully. Request ID: {request_id}, "
                       f"Version: {_config_version}")
            
        except Exception as e:
            logger.error(f"Config update failed: {str(e)}", exc_info=True)
            result.errors.append(str(e))
            result.status = UpdateStatus.FAILED
            
            # Автоматический rollback при ошибке
            if self._backup_enabled:
                result.rollback_reason = f"Auto-rollback due to error: {str(e)}"
                self._rollback()
                result.rollback_available = False
        
        finally:
            result.duration_ms = int((time.time() - start_time) * 1000)
            _update_history.append(result)
            if len(_update_history) > 100:  # Ограничение истории
                _update_history.pop(0)
        
        return result
    
    def _verify_checksum(self, update_request: UpdateRequest) -> bool:
        """Проверка checksum конфигурации"""
        try:
            config_str = json.dumps(update_request.config_data, sort_keys=True)
            
            if update_request.checksum.startswith('sha256:'):
                expected_hash = update_request.checksum[7:]
                actual_hash = hashlib.sha256(config_str.encode()).hexdigest()
                return hmac.compare_digest(expected_hash, actual_hash)
            
            elif update_request.checksum.startswith('md5:'):
                expected_hash = update_request.checksum[4:]
                actual_hash = hashlib.md5(config_str.encode()).hexdigest()
                return hmac.compare_digest(expected_hash, actual_hash)
            
            elif update_request.checksum.startswith('base64:'):
                expected_hash = update_request.checksum[7:]
                actual_hash = base64.b64encode(config_str.encode()).decode()
                return hmac.compare_digest(expected_hash, actual_hash)
            
        except Exception as e:
            logger.error(f"Checksum verification error: {str(e)}")
        
        return False
    
    def _calculate_changes(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """Расчет изменений между текущей и новой конфигурацией"""
        changes = {
            'added': {},
            'modified': {},
            'removed': {},
            'unchanged': {}
        }
        
        current_config = self.get_config()
        
        # Поиск добавленных и измененных полей
        for key, new_value in new_config.items():
            if key not in current_config:
                changes['added'][key] = new_value
            elif current_config[key] != new_value:
                changes['modified'][key] = {
                    'old': current_config[key],
                    'new': new_value
                }
            else:
                changes['unchanged'][key] = new_value
        
        # Поиск удаленных полей
        for key in current_config:
            if key not in new_config:
                changes['removed'][key] = current_config[key]
        
        return changes
    
    def _apply_config_changes(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """Применение изменений конфигурации"""
        changes = self._calculate_changes(new_config)
        
        # Применение изменений
        with _config_lock:
            # Удаление старых полей
            for key in changes['removed']:
                if '.' in key:
                    # Обработка вложенных путей
                    self._delete_nested_key(key)
                else:
                    self._config.pop(key, None)
            
            # Добавление/обновление полей
            for key, value in {**changes['added'], **changes['modified']}.items():
                if isinstance(value, dict) and 'new' in value:
                    value = value['new']
                
                if '.' in key:
                    # Установка вложенного значения
                    self._set_nested_value(key, value)
                else:
                    self._config[key] = value
        
        return changes
    
    def _set_nested_value(self, path: str, value: Any):
        """Установка значения по вложенному пути"""
        parts = path.split('.')
        config = self._config
        
        for part in parts[:-1]:
            if part not in config or not isinstance(config[part], dict):
                config[part] = {}
            config = config[part]
        
        config[parts[-1]] = value
    
    def _delete_nested_key(self, path: str):
        """Удаление значения по вложенному пути"""
        parts = path.split('.')
        config = self._config
        
        for part in parts[:-1]:
            if part not in config or not isinstance(config[part], dict):
                return
            config = config[part]
        
        config.pop(parts[-1], None)
    
    def _create_backup(self):
        """Создание backup текущей конфигурации"""
        backup = {
            'config': self._config.copy(),
            'timestamp': datetime.now().isoformat(),
            'version': _config_version
        }
        self._config_history.append(backup)
        
        # Ограничение размера истории
        if len(self._config_history) > self._max_history_size:
            self._config_history.pop(0)
    
    def _rollback(self):
        """Откат к предыдущей версии конфигурации"""
        if self._config_history:
            with _config_lock:
                backup = self._config_history.pop()
                self._config = backup['config']
                global _config_version
                _config_version = backup['version']
                logger.info(f"Config rolled back to version {_config_version}")
    
    def _save_to_history(self, update_request: UpdateRequest, request_id: str):
        """Сохранение информации об обновлении в историю"""
        history_entry = {
            'request_id': request_id,
            'timestamp': datetime.now().isoformat(),
            'source': update_request.source,
            'config_version': _config_version,
            'format': update_request.format.value,
            'dry_run': update_request.dry_run
        }
        # В реальном проекте можно сохранять в базу данных
    
    def _notify_observers(self, changes: Dict[str, Any]):
        """Уведомление наблюдателей об изменениях"""
        for observer in self._observers:
            try:
                observer(changes)
            except Exception as e:
                logger.error(f"Observer notification failed: {str(e)}")
    
    def register_observer(self, observer: Callable[[Dict], None]):
        """Регистрация наблюдателя за изменениями конфигурации"""
        self._observers.append(observer)
    
    def get_update_history(self, limit: int = 10) -> List[Dict]:
        """Получение истории обновлений"""
        return _update_history[-limit:] if _update_history else []


# Инициализация менеджера конфигурации
config_manager = ConfigManager()


def require_auth(f):
    """Декоратор для аутентификации запросов"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({'error': 'Authorization header required'}), 401
        
        # Проверка API ключа (упрощенная реализация)
        api_key = app.config.get('UPDATE_API_KEY')
        
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            if api_key and token != api_key:
                return jsonify({'error': 'Invalid API key'}), 403
        elif auth_header.startswith('Basic '):
            # Базовая аутентификация
            try:
                credentials = base64.b64decode(auth_header[6:]).decode('utf-8')
                username, password = credentials.split(':', 1)
                if username != app.config.get('UPDATE_USER') or password != app.config.get('UPDATE_PASSWORD'):
                    return jsonify({'error': 'Invalid credentials'}), 403
            except:
                return jsonify({'error': 'Invalid authentication'}), 401
        else:
            return jsonify({'error': 'Unsupported authentication method'}), 401
        
        return f(*args, **kwargs)
    return decorated_function


def parse_config_data(data: Any, content_type: str) -> Dict[str, Any]:
    """Парсинг данных конфигурации из различных форматов"""
    try:
        if content_type == 'application/json':
            if isinstance(data, (str, bytes)):
                return json.loads(data)
            return data
        
        elif content_type in ['application/x-yaml', 'text/yaml', 'text/x-yaml']:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            return yaml.safe_load(data)
        
        elif content_type == 'application/xml':
            # Упрощенный парсинг XML (в реальном проекте используйте xml.etree)
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            # Базовая конвертация XML в dict
            import re
            # Простая реализация для примера
            result = {}
            for match in re.finditer(r'<(\w+)>(.*?)</\1>', data, re.DOTALL):
                key, value = match.groups()
                result[key] = value.strip()
            return result
        
        elif content_type == 'text/plain':
            # Парсинг properties формата (key=value)
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            result = {}
            for line in data.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        result[key.strip()] = value.strip()
            return result
        
        else:
            # Попытка автоматического определения
            if isinstance(data, (str, bytes)):
                try:
                    return json.loads(data)
                except:
                    try:
                        if isinstance(data, bytes):
                            data = data.decode('utf-8')
                        return yaml.safe_load(data)
                    except:
                        pass
            
            raise ValueError(f"Unsupported content type: {content_type}")
    
    except Exception as e:
        raise ValueError(f"Failed to parse config data: {str(e)}")


def detect_format(content_type: str, data: Any) -> ConfigFormat:
    """Определение формата конфигурации"""
    content_type = content_type.lower()
    
    if 'json' in content_type:
        return ConfigFormat.JSON
    elif 'yaml' in content_type or 'yml' in content_type:
        return ConfigFormat.YAML
    elif 'xml' in content_type:
        return ConfigFormat.XML
    elif 'text/plain' in content_type:
        return ConfigFormat.PROPERTIES
    else:
        # Автоопределение по содержимому
        if isinstance(data, str):
            data_str = data
        elif isinstance(data, bytes):
            data_str = data.decode('utf-8', errors='ignore')
        else:
            return ConfigFormat.JSON
        
        data_str = data_str.strip()
        
        if data_str.startswith('{') or data_str.startswith('['):
            return ConfigFormat.JSON
        elif data_str.startswith('---') or ': ' in data_str.split('\n')[0]:
            return ConfigFormat.YAML
        elif data_str.startswith('<?xml') or data_str.startswith('<'):
            return ConfigFormat.XML
        elif '=' in data_str.split('\n')[0]:
            return ConfigFormat.PROPERTIES
        
        return ConfigFormat.JSON


@app.route('/update', methods=['POST'])
@require_auth
def update_config():
    """Эндпоинт для приема обновлений конфигурации"""
    start_time = time.time()
    
    try:
        # Получение и проверка данных
        if not request.data:
            return jsonify({
                'status': 'error',
                'error': 'No data provided',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        # Определение формата
        content_type = request.content_type or 'application/json'
        config_format = detect_format(content_type, request.data)
        
        # Парсинг данных
        config_data = parse_config_data(request.data, content_type)
        
        if not isinstance(config_data, dict):
            return jsonify({
                'status': 'error',
                'error': 'Config data must be a JSON object/dictionary',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        # Создание запроса на обновление
        update_request = UpdateRequest(
            config_data=config_data,
            format=config_format,
            source=request.remote_addr or 'unknown',
            checksum=request.headers.get('X-Config-Checksum'),
            timestamp=request.headers.get('X-Config-Timestamp'),
            dry_run=request.args.get('dry_run', 'false').lower() == 'true',
            validation_only=request.args.get('validate_only', 'false').lower() == 'true',
            priority=int(request.headers.get('X-Update-Priority', 1))
        )
        
        # Применение обновления
        result = config_manager.apply_update(update_request)
        
        # Формирование ответа
        response = {
            'request_id': result.request_id,
            'status': result.status.value,
            'config_version': result.config_version,
            'timestamp': result.timestamp.isoformat(),
            'duration_ms': result.duration_ms,
            'applied_changes': result.applied_changes,
            'rollback_available': result.rollback_available
        }
        
        if result.errors:
            response['errors'] = result.errors
        if result.warnings:
            response['warnings'] = result.warnings
        if result.rollback_reason:
            response['rollback_reason'] = result.rollback_reason
        
        # Определение HTTP статуса
        http_status = 200
        if result.status == UpdateStatus.REJECTED:
            http_status = 400
        elif result.status == UpdateStatus.FAILED:
            http_status = 500
        
        logger.info(f"Update request {result.request_id} completed with status {result.status.value} "
                   f"in {result.duration_ms}ms")
        
        return jsonify(response), http_status
        
    except ValueError as e:
        logger.error(f"Invalid request data: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': 'Internal server error',
            'timestamp': datetime.now().isoformat(),
            'request_duration_ms': int((time.time() - start_time) * 1000)
        }), 500


@app.route('/update/status', methods=['GET'])
def get_update_status():
    """Получение статуса последних обновлений"""
    try:
        limit = min(int(request.args.get('limit', 10)), 50)
        
        history = config_manager.get_update_history(limit)
        
        return jsonify({
            'current_version': _config_version,
            'last_update_time': _last_update_time.isoformat() if _last_update_time else None,
            'total_updates': len(_update_history),
            'recent_updates': [
                {
                    'request_id': item.request_id,
                    'status': item.status.value,
                    'timestamp': item.timestamp.isoformat(),
                    'config_version': item.config_version,
                    'duration_ms': item.duration_ms
                }
                for item in history
            ]
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get update status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/update/rollback', methods=['POST'])
@require_auth
def rollback_config():
    """Эндпоинт для отката конфигурации"""
    try:
        version = request.args.get('version')
        
        if version:
            # В реальном проекте реализовать откат к конкретной версии
            return jsonify({
                'status': 'error',
                'error': 'Rollback to specific version not implemented',
                'timestamp': datetime.now().isoformat()
            }), 501
        
        # Откат к предыдущей версии
        with _config_lock:
            if config_manager._config_history:
                config_manager._rollback()
                return jsonify({
                    'status': 'success',
                    'message': f'Rolled back to version {_config_version}',
                    'config_version': _config_version,
                    'timestamp': datetime.now().isoformat()
                }), 200
            else:
                return jsonify({
                    'status': 'error',
                    'error': 'No backup available for rollback',
                    'timestamp': datetime.now().isoformat()
                }), 400
                
    except Exception as e:
        logger.error(f"Rollback failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


# Конфигурация приложения
app.config.update(
    UPDATE_API_KEY='your-api-key-here',  # Замените на реальный ключ
    UPDATE_USER='admin',
    UPDATE_PASSWORD='secure-password-here',
    JSONIFY_PRETTYPRINT_REGULAR=True,
    MAX_CONTENT_LENGTH=10 * 1024 * 1024  # 10MB max config size
)


# Регистрация стандартных схем валидации
validator = ConfigValidator()
validator.register_schema('app_config', {
    'type': 'object',
    'properties': {
        'version': {'type': 'string', 'required': True},
        'environment': {'type': 'string', 'required': True},
        'debug': {'type': 'boolean'},
        'log_level': {'type': 'string', 'enum': ['DEBUG', 'INFO', 'WARNING', 'ERROR']},
        'database': {
            'type': 'object',
            'properties': {
                'host': {'type': 'string', 'required': True},
                'port': {'type': 'integer', 'minimum': 1, 'maximum': 65535},
                'name': {'type': 'string', 'required': True},
                'user': {'type': 'string'},
                'password': {'type': 'string'}
            }
        }
    }
})

# Пример наблюдателя для логирования изменений
def log_config_changes(changes: Dict[str, Any]):
    """Наблюдатель для логирования изменений конфигурации"""
    if changes.get('added'):
        logger.info(f"Config fields added: {list(changes['added'].keys())}")
    if changes.get('modified'):
        logger.info(f"Config fields modified: {list(changes['modified'].keys())}")
    if changes.get('removed'):
        logger.info(f"Config fields removed: {list(changes['removed'].keys())}")

config_manager.register_observer(log_config_changes)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)