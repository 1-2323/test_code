from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc, text, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime, date
import json
import logging
import traceback
import uuid
import hashlib
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading
from functools import wraps
from decimal import Decimal
import re

# Инициализация Flask приложения
app = Flask(__name__)

# Конфигурация базы данных
app.config.update(
    SQLALCHEMY_DATABASE_URI='postgresql://user:password@localhost/dbname',  # Замените на реальные данные
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={
        'pool_size': 10,
        'max_overflow': 20,
        'pool_timeout': 30,
        'pool_recycle': 1800,
    },
    IMPORT_BATCH_SIZE=100,
    IMPORT_MAX_RECORDS=10000,
    IMPORT_ALLOWED_MODELS={'User', 'Product', 'Order', 'Category', 'Invoice'},
    IMPORT_REQUIRED_API_KEY=True,
    SECRET_KEY='your-secret-key-here',
    JSONIFY_PRETTYPRINT_REGULAR=True
)

# Инициализация SQLAlchemy
db = SQLAlchemy(app)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Блокировки для конкурентного доступа
_import_lock = threading.RLock()
_active_imports: Dict[str, Dict] = {}


class ImportStatus(Enum):
    """Статусы импорта"""
    PENDING = "pending"
    PROCESSING = "processing"
    VALIDATING = "validating"
    VALIDATED = "validated"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    ROLLED_BACK = "rolled_back"


class ValidationResult(Enum):
    """Результаты валидации"""
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class ImportStatistics:
    """Статистика импорта"""
    total_records: int = 0
    processed_records: int = 0
    successful_records: int = 0
    failed_records: int = 0
    skipped_records: int = 0
    validation_errors: int = 0
    validation_warnings: int = 0
    duplicates_found: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Длительность импорта в секундах"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    @property
    def success_rate(self) -> float:
        """Процент успешных записей"""
        if self.processed_records == 0:
            return 0.0
        return (self.successful_records / self.processed_records) * 100


@dataclass
class ImportRecord:
    """Запись для импорта"""
    data: Dict[str, Any]
    model_name: str
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    validation_result: ValidationResult = ValidationResult.PENDING
    import_result: Optional[bool] = None
    error_message: Optional[str] = None
    record_id: Optional[str] = None
    is_duplicate: bool = False
    external_id: Optional[str] = None


@dataclass
class ImportJob:
    """Задача импорта"""
    job_id: str
    status: ImportStatus
    model_name: str
    records: List[ImportRecord]
    statistics: ImportStatistics
    created_at: datetime
    updated_at: datetime
    options: Dict[str, Any]
    user_id: Optional[str] = None
    source_system: Optional[str] = None
    error_log: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# Модели базы данных
class ImportHistory(db.Model):
    """История импортов"""
    __tablename__ = 'import_history'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = db.Column(db.String(50), nullable=False, index=True)
    model_name = db.Column(db.String(100), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, index=True)
    total_records = db.Column(db.Integer, nullable=False)
    successful_records = db.Column(db.Integer, default=0)
    failed_records = db.Column(db.Integer, default=0)
    user_id = db.Column(db.String(50), nullable=True)
    source_system = db.Column(db.String(100), nullable=True)
    options = db.Column(JSONB, default=dict)
    error_log = db.Column(JSONB, default=list)
    warnings = db.Column(JSONB, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Float, nullable=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'id': self.id,
            'job_id': self.job_id,
            'model_name': self.model_name,
            'status': self.status,
            'total_records': self.total_records,
            'successful_records': self.successful_records,
            'failed_records': self.failed_records,
            'user_id': self.user_id,
            'source_system': self.source_system,
            'options': self.options,
            'error_log': self.error_log,
            'warnings': self.warnings,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_seconds': self.duration_seconds
        }


class FailedImport(db.Model):
    """Неудачные импорты для повторной обработки"""
    __tablename__ = 'failed_imports'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = db.Column(db.String(50), nullable=False, index=True)
    model_name = db.Column(db.String(100), nullable=False, index=True)
    original_data = db.Column(JSONB, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    validation_errors = db.Column(JSONB, default=list)
    external_id = db.Column(db.String(255), nullable=True, index=True)
    import_history_id = db.Column(db.String(36), db.ForeignKey('import_history.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    import_history = db.relationship('ImportHistory', backref='failed_imports')


# Пример моделей для импорта
class User(db.Model):
    """Пример модели пользователя"""
    __tablename__ = 'users'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    username = db.Column(db.String(100), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    metadata = db.Column(JSONB, default=dict)
    
    # Внешние ключи и связи будут добавлены по мере необходимости


class Product(db.Model):
    """Пример модели продукта"""
    __tablename__ = 'products'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sku = db.Column(db.String(100), nullable=False, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    category_id = db.Column(db.String(36), db.ForeignKey('categories.id'), nullable=True)
    stock_quantity = db.Column(db.Integer, default=0)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    attributes = db.Column(JSONB, default=dict)
    
    category = db.relationship('Category', backref='products')


class Order(db.Model):
    """Пример модели заказа"""
    __tablename__ = 'orders'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='pending')
    items = db.Column(JSONB, default=list)  # Упрощенная структура элементов заказа
    shipping_address = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = db.relationship('User', backref='orders')


class Category(db.Model):
    """Пример модели категории"""
    __tablename__ = 'categories'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    slug = db.Column(db.String(255), nullable=False, unique=True, index=True)
    parent_id = db.Column(db.String(36), db.ForeignKey('categories.id'), nullable=True)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    parent = db.relationship('Category', remote_side=[id], backref='children')


class Invoice(db.Model):
    """Пример модели счета"""
    __tablename__ = 'invoices'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    order_id = db.Column(db.String(36), db.ForeignKey('orders.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(50), nullable=False, default='unpaid')
    due_date = db.Column(db.Date, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    line_items = db.Column(JSONB, default=list)
    
    order = db.relationship('Order', backref='invoices')


class DataImporter:
    """Основной класс для импорта данных"""
    
    def __init__(self):
        self._model_registry = self._build_model_registry()
        self._validators = {}
        self._transformers = {}
        self._register_default_validators()
        self._register_default_transformers()
    
    def _build_model_registry(self) -> Dict[str, Any]:
        """Регистрация доступных моделей"""
        registry = {}
        
        # Автоматическое обнаружение моделей SQLAlchemy
        models = [User, Product, Order, Category, Invoice]
        
        for model in models:
            model_name = model.__name__
            
            # Получение информации о полях модели
            mapper = inspect(model)
            fields_info = {}
            
            for column in mapper.columns:
                field_info = {
                    'type': str(column.type),
                    'nullable': column.nullable,
                    'primary_key': column.primary_key,
                    'unique': column.unique,
                    'default': column.default.arg if column.default else None,
                    'foreign_key': bool(column.foreign_keys)
                }
                fields_info[column.name] = field_info
            
            registry[model_name] = {
                'model': model,
                'fields': fields_info,
                'relationships': {rel.key: rel for rel in mapper.relationships},
                'table_name': model.__tablename__
            }
        
        return registry
    
    def _register_default_validators(self):
        """Регистрация стандартных валидаторов"""
        # Валидаторы типов данных
        self._validators['string'] = lambda x, **kwargs: isinstance(x, str)
        self._validators['integer'] = lambda x, **kwargs: isinstance(x, int)
        self._validators['float'] = lambda x, **kwargs: isinstance(x, (int, float))
        self._validators['boolean'] = lambda x, **kwargs: isinstance(x, bool)
        self._validators['email'] = lambda x, **kwargs: (
            isinstance(x, str) and 
            re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', x) is not None
        )
        self._validators['date'] = lambda x, **kwargs: (
            isinstance(x, str) and 
            self._try_parse_date(x) is not None
        )
        
        # Валидаторы ограничений
        self._validators['required'] = lambda x, **kwargs: x is not None and x != ''
        self._validators['min_length'] = lambda x, min_len, **kwargs: (
            isinstance(x, str) and len(x) >= min_len
        )
        self._validators['max_length'] = lambda x, max_len, **kwargs: (
            isinstance(x, str) and len(x) <= max_len
        )
        self._validators['min_value'] = lambda x, min_val, **kwargs: x >= min_val
        self._validators['max_value'] = lambda x, max_val, **kwargs: x <= max_val
    
    def _register_default_transformers(self):
        """Регистрация стандартных трансформеров"""
        self._transformers['trim'] = lambda x: x.strip() if isinstance(x, str) else x
        self._transformers['lowercase'] = lambda x: x.lower() if isinstance(x, str) else x
        self._transformers['uppercase'] = lambda x: x.upper() if isinstance(x, str) else x
        self._transformers['parse_date'] = lambda x: self._try_parse_date(x) if isinstance(x, str) else x
        self._transformers['parse_decimal'] = lambda x: Decimal(str(x)) if x is not None else None
        self._transformers['generate_uuid'] = lambda x: str(uuid.uuid4()) if x is None else x
    
    def _try_parse_date(self, date_str: str) -> Optional[date]:
        """Попытка парсинга даты из строки"""
        date_formats = [
            '%Y-%m-%d',
            '%d.%m.%Y',
            '%m/%d/%Y',
            '%Y/%m/%d',
            '%d-%m-%Y',
            '%Y%m%d'
        ]
        
        for date_format in date_formats:
            try:
                return datetime.strptime(date_str, date_format).date()
            except ValueError:
                continue
        
        return None
    
    def validate_record(self, record: Dict[str, Any], model_name: str) -> Tuple[ValidationResult, List[str], List[str]]:
        """
        Валидация записи для импорта
        
        Returns:
            (результат, ошибки, предупреждения)
        """
        errors = []
        warnings = []
        
        if model_name not in self._model_registry:
            errors.append(f"Unknown model: {model_name}")
            return ValidationResult.INVALID, errors, warnings
        
        model_info = self._model_registry[model_name]
        fields_info = model_info['fields']
        
        # Проверка обязательных полей
        for field_name, field_info in fields_info.items():
            if not field_info['nullable'] and field_info['default'] is None and not field_info['primary_key']:
                if field_name not in record:
                    errors.append(f"Required field missing: {field_name}")
        
        # Проверка типов данных и ограничений
        for field_name, field_value in record.items():
            if field_name in fields_info:
                field_info = fields_info[field_name]
                
                # Преобразование типа перед валидацией
                converted_value = self._convert_value(field_value, field_info['type'])
                
                if converted_value is None and field_value is not None:
                    errors.append(f"Invalid type for field '{field_name}': expected {field_info['type']}")
                    continue
                
                # Валидация уникальности (проверяется позже при сохранении)
                if field_info['unique']:
                    warnings.append(f"Field '{field_name}' must be unique")
        
        # Кастомные валидации в зависимости от модели
        if model_name == 'User':
            if 'email' in record and not self._validators['email'](record['email']):
                errors.append("Invalid email format")
        
        elif model_name == 'Product':
            if 'price' in record:
                try:
                    price = Decimal(str(record['price']))
                    if price <= 0:
                        errors.append("Price must be greater than 0")
                except:
                    errors.append("Invalid price format")
        
        # Определение результата валидации
        if errors:
            return ValidationResult.INVALID, errors, warnings
        elif warnings:
            return ValidationResult.WARNING, errors, warnings
        else:
            return ValidationResult.VALID, errors, warnings
    
    def _convert_value(self, value: Any, field_type: str) -> Any:
        """Конвертация значения к нужному типу"""
        if value is None:
            return None
        
        try:
            # Определение базового типа из строки типа SQLAlchemy
            if 'VARCHAR' in field_type or 'TEXT' in field_type or 'CHAR' in field_type:
                return str(value)
            
            elif 'INTEGER' in field_type or 'INT' in field_type:
                return int(value)
            
            elif 'NUMERIC' in field_type or 'DECIMAL' in field_type or 'FLOAT' in field_type:
                return Decimal(str(value))
            
            elif 'BOOLEAN' in field_type or 'BOOL' in field_type:
                if isinstance(value, str):
                    return value.lower() in ('true', 'yes', '1', 't')
                return bool(value)
            
            elif 'DATETIME' in field_type:
                if isinstance(value, str):
                    return datetime.fromisoformat(value.replace('Z', '+00:00'))
                elif isinstance(value, (int, float)):
                    return datetime.fromtimestamp(value)
            
            elif 'DATE' in field_type:
                if isinstance(value, str):
                    return self._try_parse_date(value)
                elif isinstance(value, (int, float)):
                    return datetime.fromtimestamp(value).date()
            
            elif 'JSON' in field_type or 'JSONB' in field_type:
                if isinstance(value, str):
                    return json.loads(value)
                return value
            
            else:
                return value
                
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to convert value {value} to type {field_type}: {str(e)}")
            return None
    
    def transform_record(self, record: Dict[str, Any], model_name: str) -> Dict[str, Any]:
        """Трансформация записи перед сохранением"""
        transformed = record.copy()
        
        if model_name not in self._model_registry:
            return transformed
        
        model_info = self._model_registry[model_name]
        
        # Применение трансформеров в зависимости от модели
        if model_name == 'User':
            if 'email' in transformed and isinstance(transformed['email'], str):
                transformed['email'] = transformed['email'].lower().strip()
            
            if 'username' in transformed and isinstance(transformed['username'], str):
                transformed['username'] = transformed['username'].strip()
        
        elif model_name == 'Product':
            if 'sku' in transformed and isinstance(transformed['sku'], str):
                transformed['sku'] = transformed['sku'].upper().strip()
        
        # Генерация ID для новых записей
        if 'id' not in transformed:
            transformed['id'] = str(uuid.uuid4())
        
        # Добавление временных меток
        current_time = datetime.utcnow()
        if 'created_at' not in transformed:
            transformed['created_at'] = current_time
        if 'updated_at' not in transformed:
            transformed['updated_at'] = current_time
        
        return transformed
    
    def check_duplicates(self, record: Dict[str, Any], model_name: str) -> bool:
        """Проверка на дубликаты"""
        if model_name not in self._model_registry:
            return False
        
        model_info = self._model_registry[model_name]
        model_class = model_info['model']
        
        # Проверка уникальных полей
        for field_name, field_info in model_info['fields'].items():
            if field_info['unique'] and field_name in record:
                existing = model_class.query.filter(
                    getattr(model_class, field_name) == record[field_name]
                ).first()
                
                if existing:
                    return True
        
        return False
    
    def save_record(self, record: Dict[str, Any], model_name: str, 
                   update_existing: bool = False) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Сохранение записи в базу данных
        
        Returns:
            (успех, id_записи, сообщение_об_ошибке)
        """
        try:
            if model_name not in self._model_registry:
                return False, None, f"Unknown model: {model_name}"
            
            model_info = self._model_registry[model_name]
            model_class = model_info['model']
            
            # Поиск существующей записи по уникальным полям
            existing_record = None
            if update_existing:
                for field_name, field_info in model_info['fields'].items():
                    if field_info['unique'] and field_name in record:
                        existing_record = model_class.query.filter(
                            getattr(model_class, field_name) == record[field_name]
                        ).first()
                        
                        if existing_record:
                            break
            
            if existing_record and update_existing:
                # Обновление существующей записи
                for key, value in record.items():
                    if hasattr(existing_record, key) and key != 'id':
                        setattr(existing_record, key, value)
                
                existing_record.updated_at = datetime.utcnow()
                db.session.add(existing_record)
                record_id = existing_record.id
                operation = 'updated'
                
            else:
                # Создание новой записи
                new_record = model_class(**record)
                db.session.add(new_record)
                record_id = new_record.id
                operation = 'created'
            
            return True, record_id, None
            
        except exc.IntegrityError as e:
            db.session.rollback()
            error_msg = f"Integrity error: {str(e.orig)}"
            logger.error(f"Integrity error saving {model_name}: {error_msg}")
            return False, None, error_msg
            
        except exc.DataError as e:
            db.session.rollback()
            error_msg = f"Data error: {str(e.orig)}"
            logger.error(f"Data error saving {model_name}: {error_msg}")
            return False, None, error_msg
            
        except Exception as e:
            db.session.rollback()
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Error saving {model_name}: {error_msg}", exc_info=True)
            return False, None, error_msg


class ImportService:
    """Сервис управления импортом"""
    
    def __init__(self):
        self.importer = DataImporter()
        self._active_jobs: Dict[str, ImportJob] = {}
    
    def create_import_job(self, model_name: str, records: List[Dict], 
                         user_id: Optional[str] = None,
                         source_system: Optional[str] = None,
                         options: Optional[Dict] = None) -> ImportJob:
        """Создание задачи импорта"""
        job_id = hashlib.md5(
            f"{datetime.utcnow().isoformat()}{model_name}{len(records)}".encode()
        ).hexdigest()[:16]
        
        now = datetime.utcnow()
        
        import_records = []
        for i, record in enumerate(records):
            external_id = record.get('id') or record.get('external_id') or f"record_{i}"
            import_record = ImportRecord(
                data=record,
                model_name=model_name,
                external_id=external_id
            )
            import_records.append(import_record)
        
        job = ImportJob(
            job_id=job_id,
            status=ImportStatus.PENDING,
            model_name=model_name,
            records=import_records,
            statistics=ImportStatistics(
                total_records=len(records),
                start_time=now
            ),
            created_at=now,
            updated_at=now,
            options=options or {},
            user_id=user_id,
            source_system=source_system
        )
        
        with _import_lock:
            self._active_jobs[job_id] = job
            _active_imports[job_id] = {
                'status': job.status.value,
                'model': model_name,
                'records_count': len(records),
                'started_at': now.isoformat()
            }
        
        # Сохранение в историю
        history_entry = ImportHistory(
            job_id=job_id,
            model_name=model_name,
            status=job.status.value,
            total_records=len(records),
            user_id=user_id,
            source_system=source_system,
            options=options or {}
        )
        db.session.add(history_entry)
        db.session.commit()
        
        logger.info(f"Created import job {job_id} for {model_name} with {len(records)} records")
        
        return job
    
    def process_import_job(self, job_id: str, async_mode: bool = False) -> ImportJob:
        """Обработка задачи импорта"""
        with _import_lock:
            if job_id not in self._active_jobs:
                raise ValueError(f"Job {job_id} not found")
            
            job = self._active_jobs[job_id]
            job.status = ImportStatus.PROCESSING
            job.updated_at = datetime.utcnow()
        
        if async_mode:
            # Запуск в отдельном потоке для асинхронной обработки
            thread = threading.Thread(
                target=self._process_job_sync,
                args=(job_id,),
                daemon=True
            )
            thread.start()
            return job
        else:
            return self._process_job_sync(job_id)
    
    def _process_job_sync(self, job_id: str) -> ImportJob:
        """Синхронная обработка задачи импорта"""
        with _import_lock:
            job = self._active_jobs[job_id]
            job.status = ImportStatus.VALIDATING
            job.updated_at = datetime.utcnow()
        
        try:
            # 1. Валидация записей
            logger.info(f"Validating records for job {job_id}")
            for record in job.records:
                validation_result, errors, warnings = self.importer.validate_record(
                    record.data, 
                    job.model_name
                )
                
                record.validation_result = validation_result
                record.validation_errors = errors
                record.validation_warnings = warnings
                
                if validation_result == ValidationResult.INVALID:
                    job.statistics.validation_errors += 1
                    job.error_log.extend(errors)
                elif validation_result == ValidationResult.WARNING:
                    job.statistics.validation_warnings += 1
                    job.warnings.extend(warnings)
            
            # Обновление статуса после валидации
            with _import_lock:
                job.status = ImportStatus.VALIDATED
                job.updated_at = datetime.utcnow()
            
            # 2. Проверка на дубликаты
            logger.info(f"Checking duplicates for job {job_id}")
            for record in job.records:
                if record.validation_result == ValidationResult.VALID:
                    record.is_duplicate = self.importer.check_duplicates(
                        record.data, 
                        job.model_name
                    )
                    if record.is_duplicate:
                        job.statistics.duplicates_found += 1
            
            # 3. Импорт записей
            with _import_lock:
                job.status = ImportStatus.IMPORTING
                job.updated_at = datetime.utcnow()
            
            logger.info(f"Importing records for job {job_id}")
            batch_size = app.config['IMPORT_BATCH_SIZE']
            
            for i in range(0, len(job.records), batch_size):
                batch = job.records[i:i + batch_size]
                
                for record in batch:
                    job.statistics.processed_records += 1
                    
                    if record.validation_result != ValidationResult.VALID:
                        job.statistics.failed_records += 1
                        record.import_result = False
                        record.error_message = "; ".join(record.validation_errors)
                        continue
                    
                    if record.is_duplicate and not job.options.get('allow_duplicates', False):
                        job.statistics.skipped_records += 1
                        record.import_result = None
                        continue
                    
                    # Трансформация записи
                    transformed_data = self.importer.transform_record(
                        record.data, 
                        job.model_name
                    )
                    
                    # Сохранение в базу
                    success, record_id, error = self.importer.save_record(
                        transformed_data,
                        job.model_name,
                        update_existing=job.options.get('update_existing', False)
                    )
                    
                    record.import_result = success
                    record.record_id = record_id
                    
                    if success:
                        job.statistics.successful_records += 1
                    else:
                        job.statistics.failed_records += 1
                        record.error_message = error
                        
                        # Сохранение неудачной записи для повторной обработки
                        failed_import = FailedImport(
                            job_id=job_id,
                            model_name=job.model_name,
                            original_data=record.data,
                            error_message=error,
                            validation_errors=record.validation_errors,
                            external_id=record.external_id,
                            import_history_id=None  # Можно связать с историей
                        )
                        db.session.add(failed_import)
                
                # Коммит батча
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Batch commit failed: {str(e)}")
                    # Отметить все записи в батче как неудачные
                    for record in batch:
                        if record.import_result is None:
                            record.import_result = False
                            record.error_message = f"Batch commit failed: {str(e)}"
                            job.statistics.failed_records += 1
            
            # 4. Завершение задачи
            job.statistics.end_time = datetime.utcnow()
            
            with _import_lock:
                if job.statistics.failed_records > 0 and job.statistics.successful_records > 0:
                    job.status = ImportStatus.PARTIAL
                elif job.statistics.failed_records == job.statistics.total_records:
                    job.status = ImportStatus.FAILED
                else:
                    job.status = ImportStatus.COMPLETED
                
                job.updated_at = datetime.utcnow()
            
            # Обновление записи в истории
            history_entry = ImportHistory.query.filter_by(job_id=job_id).first()
            if history_entry:
                history_entry.status = job.status.value
                history_entry.successful_records = job.statistics.successful_records
                history_entry.failed_records = job.statistics.failed_records
                history_entry.completed_at = job.statistics.end_time
                history_entry.duration_seconds = job.statistics.duration_seconds
                history_entry.error_log = job.error_log[:100]  # Ограничение
                history_entry.warnings = job.warnings[:100]
                db.session.commit()
            
            logger.info(f"Import job {job_id} completed with status {job.status.value}. "
                       f"Success rate: {job.statistics.success_rate:.1f}%")
            
        except Exception as e:
            with _import_lock:
                job.status = ImportStatus.FAILED
                job.updated_at = datetime.utcnow()
                job.error_log.append(f"Processing error: {str(e)}")
            
            logger.error(f"Import job {job_id} failed: {str(e)}", exc_info=True)
        
        finally:
            with _import_lock:
                if job_id in _active_imports:
                    _active_imports[job_id]['status'] = job.status.value
                    _active_imports[job_id]['completed_at'] = datetime.utcnow().isoformat()
        
        return job
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Получение статуса задачи"""
        with _import_lock:
            if job_id in self._active_jobs:
                job = self._active_jobs[job_id]
                return self._job_to_dict(job)
            
            # Поиск в истории
            history_entry = ImportHistory.query.filter_by(job_id=job_id).first()
            if history_entry:
                return history_entry.to_dict()
        
        return None
    
    def _job_to_dict(self, job: ImportJob) -> Dict[str, Any]:
        """Конвертация задачи в словарь"""
        return {
            'job_id': job.job_id,
            'status': job.status.value,
            'model_name': job.model_name,
            'created_at': job.created_at.isoformat(),
            'updated_at': job.updated_at.isoformat(),
            'statistics': {
                'total_records': job.statistics.total_records,
                'processed_records': job.statistics.processed_records,
                'successful_records': job.statistics.successful_records,
                'failed_records': job.statistics.failed_records,
                'skipped_records': job.statistics.skipped_records,
                'validation_errors': job.statistics.validation_errors,
                'validation_warnings': job.statistics.validation_warnings,
                'duplicates_found': job.statistics.duplicates_found,
                'start_time': job.statistics.start_time.isoformat() if job.statistics.start_time else None,
                'end_time': job.statistics.end_time.isoformat() if job.statistics.end_time else None,
                'duration_seconds': job.statistics.duration_seconds,
                'success_rate': job.statistics.success_rate
            },
            'options': job.options,
            'user_id': job.user_id,
            'source_system': job.source_system,
            'error_count': len(job.error_log),
            'warning_count': len(job.warnings)
        }


# Инициализация сервиса
import_service = ImportService()


# Декора