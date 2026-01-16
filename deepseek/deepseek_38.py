import csv
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Protocol
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import logging
from decimal import Decimal, InvalidOperation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Исключение для ошибок валидации"""
    def __init__(self, field: str, message: str, value: Any = None):
        self.field = field
        self.message = message
        self.value = value
        super().__init__(f"{field}: {message} (value: {value})")


@dataclass
class ValidationResult:
    """Результат валидации строки данных"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    cleaned_data: Optional[Dict[str, Any]] = None


class FieldValidator(Protocol):
    """Протокол для валидаторов полей"""
    def validate(self, value: Any, field_name: str) -> tuple[bool, Optional[str], Any]:
        ...


class DataSchema:
    """Схема данных для валидации"""
    
    def __init__(self):
        # Словарь валидаторов для каждого поля
        self.validators: Dict[str, List[FieldValidator]] = {}
        # Обязательные поля
        self.required_fields: List[str] = []
        # Типы полей для информационных целей
        self.field_types: Dict[str, str] = {}
    
    def add_field(
        self,
        field_name: str,
        validators: List[FieldValidator],
        is_required: bool = True,
        field_type: str = "string"
    ) -> None:
        """
        Добавление поля в схему
        
        Args:
            field_name: Имя поля
            validators: Список валидаторов для поля
            is_required: Обязательное ли поле
            field_type: Тип поля для информации
        """
        self.validators[field_name] = validators
        if is_required:
            self.required_fields.append(field_name)
        self.field_types[field_name] = field_type
    
    def get_field_type(self, field_name: str) -> str:
        """Получение типа поля"""
        return self.field_types.get(field_name, "unknown")


# Конкретные валидаторы полей
class RequiredValidator:
    """Валидатор проверки обязательного поля"""
    
    def validate(self, value: Any, field_name: str) -> tuple[bool, Optional[str], Any]:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return False, "Field is required", None
        return True, None, value


class StringValidator:
    """Валидатор строковых значений"""
    
    def __init__(self, min_length: int = 0, max_length: Optional[int] = None):
        self.min_length = min_length
        self.max_length = max_length
    
    def validate(self, value: Any, field_name: str) -> tuple[bool, Optional[str], Any]:
        if not isinstance(value, str):
            value = str(value) if value is not None else ""
        
        value = value.strip()
        
        if len(value) < self.min_length:
            return False, f"Minimum length is {self.min_length}", value
        
        if self.max_length and len(value) > self.max_length:
            return False, f"Maximum length is {self.max_length}", value
        
        return True, None, value


class IntegerValidator:
    """Валидатор целочисленных значений"""
    
    def __init__(self, min_value: Optional[int] = None, max_value: Optional[int] = None):
        self.min_value = min_value
        self.max_value = max_value
    
    def validate(self, value: Any, field_name: str) -> tuple[bool, Optional[str], Any]:
        try:
            if value is None or (isinstance(value, str) and value.strip() == ""):
                return False, "Cannot convert empty value to integer", None
            
            int_value = int(value)
            
            if self.min_value is not None and int_value < self.min_value:
                return False, f"Minimum value is {self.min_value}", int_value
            
            if self.max_value is not None and int_value > self.max_value:
                return False, f"Maximum value is {self.max_value}", int_value
            
            return True, None, int_value
            
        except (ValueError, TypeError):
            return False, f"Invalid integer value: {value}", None


class DecimalValidator:
    """Валидатор десятичных значений"""
    
    def __init__(
        self,
        min_value: Optional[Decimal] = None,
        max_value: Optional[Decimal] = None,
        precision: int = 2
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.precision = precision
    
    def validate(self, value: Any, field_name: str) -> tuple[bool, Optional[str], Any]:
        try:
            if value is None or (isinstance(value, str) and value.strip() == ""):
                return False, "Cannot convert empty value to decimal", None
            
            # Преобразуем в Decimal
            decimal_value = Decimal(str(value)).quantize(Decimal(f'1.{self.precision}'))
            
            if self.min_value is not None and decimal_value < self.min_value:
                return False, f"Minimum value is {self.min_value}", decimal_value
            
            if self.max_value is not None and decimal_value > self.max_value:
                return False, f"Maximum value is {self.max_value}", decimal_value
            
            return True, None, float(decimal_value)  # Преобразуем к float для JSON
            
        except (InvalidOperation, ValueError, TypeError):
            return False, f"Invalid decimal value: {value}", None


class DateValidator:
    """Валидатор дат"""
    
    def __init__(self, date_format: str = "%Y-%m-%d"):
        self.date_format = date_format
    
    def validate(self, value: Any, field_name: str) -> tuple[bool, Optional[str], Any]:
        try:
            if not value:
                return False, "Date value is required", None
            
            # Пытаемся распарсить дату
            date_obj = datetime.strptime(str(value).strip(), self.date_format)
            return True, None, date_obj.strftime(self.date_format)
            
        except ValueError:
            return False, f"Invalid date format. Expected: {self.date_format}", None


class EmailValidator:
    """Валидатор email адресов"""
    
    def validate(self, value: Any, field_name: str) -> tuple[bool, Optional[str], Any]:
        if not value:
            return False, "Email is required", None
        
        email = str(value).strip().lower()
        
        # Базовая проверка формата email
        if "@" not in email or "." not in email.split("@")[-1]:
            return False, "Invalid email format", email
        
        return True, None, email


class DataValidator:
    """Валидатор данных по схеме"""
    
    def __init__(self, schema: DataSchema):
        self.schema = schema
    
    def validate_row(self, row_data: Dict[str, Any]) -> ValidationResult:
        """
        Валидация одной строки данных
        
        Args:
            row_data: Словарь с данными строки
            
        Returns:
            Результат валидации
        """
        errors = []
        cleaned_data = {}
        
        # Проверка обязательных полей
        for field_name in self.schema.required_fields:
            if field_name not in row_data or row_data[field_name] in (None, "", []):
                errors.append(f"Missing required field: {field_name}")
        
        # Валидация каждого поля
        for field_name, value in row_data.items():
            # Пропускаем поля, которых нет в схеме
            if field_name not in self.schema.validators:
                cleaned_data[field_name] = value
                continue
            
            # Получаем валидаторы для поля
            field_validators = self.schema.validators.get(field_name, [])
            
            # Последовательно применяем все валидаторы
            current_value = value
            for validator in field_validators:
                is_valid, error_msg, cleaned_value = validator.validate(
                    current_value,
                    field_name
                )
                
                if not is_valid:
                    errors.append(f"{field_name}: {error_msg}")
                    break
                
                current_value = cleaned_value
            else:
                # Все валидаторы пройдены успешно
                cleaned_data[field_name] = current_value
        
        # Возвращаем результат валидации
        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            cleaned_data=cleaned_data if is_valid else None
        )


class DataImporter:
    """Импортер данных из файлов"""
    
    def __init__(self, validator: DataValidator):
        self.validator = validator
        self.stats = {
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "errors": []
        }
    
    def import_from_csv(
        self,
        file_path: Union[str, Path],
        delimiter: str = ",",
        encoding: str = "utf-8"
    ) -> List[Dict[str, Any]]:
        """
        Импорт данных из CSV файла
        
        Returns:
            Список валидных строк данных
        """
        file_path = Path(file_path)
        valid_data = []
        
        logger.info(f"Starting CSV import from {file_path}")
        
        try:
            with open(file_path, 'r', encoding=encoding) as csv_file:
                # Автоматическое определение диалекта CSV
                sample = csv_file.read(1024)
                csv_file.seek(0)
                
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except csv.Error:
                    dialect = csv.excel
                    dialect.delimiter = delimiter
                
                reader = csv.DictReader(csv_file, dialect=dialect)
                
                for row_num, row in enumerate(reader, 1):
                    self.stats["total_rows"] += 1
                    
                    # Валидируем строку
                    result = self.validator.validate_row(row)
                    
                    if result.is_valid:
                        valid_data.append(result.cleaned_data)
                        self.stats["valid_rows"] += 1
                    else:
                        self.stats["invalid_rows"] += 1
                        self.stats["errors"].append({
                            "row": row_num,
                            "errors": result.errors,
                            "raw_data": row
                        })
                        logger.warning(f"Row {row_num} invalid: {result.errors}")
            
            logger.info(
                f"CSV import completed. "
                f"Valid: {self.stats['valid_rows']}, "
                f"Invalid: {self.stats['invalid_rows']}, "
                f"Total: {self.stats['total_rows']}"
            )
            
        except (IOError, csv.Error) as e:
            logger.error(f"Error reading CSV file: {e}")
            raise
        
        return valid_data
    
    def import_from_json(
        self,
        file_path: Union[str, Path],
        encoding: str = "utf-8"
    ) -> List[Dict[str, Any]]:
        """
        Импорт данных из JSON файла
        
        Returns:
            Список валидных строк данных
        """
        file_path = Path(file_path)
        valid_data = []
        
        logger.info(f"Starting JSON import from {file_path}")
        
        try:
            with open(file_path, 'r', encoding=encoding) as json_file:
                data = json.load(json_file)
                
                # Проверяем, что данные - это список
                if not isinstance(data, list):
                    raise ValueError("JSON data should be an array of objects")
                
                for row_num, row in enumerate(data, 1):
                    self.stats["total_rows"] += 1
                    
                    # Валидируем строку
                    result = self.validator.validate_row(row)
                    
                    if result.is_valid:
                        valid_data.append(result.cleaned_data)
                        self.stats["valid_rows"] += 1
                    else:
                        self.stats["invalid_rows"] += 1
                        self.stats["errors"].append({
                            "row": row_num,
                            "errors": result.errors,
                            "raw_data": row
                        })
                        logger.warning(f"Row {row_num} invalid: {result.errors}")
            
            logger.info(
                f"JSON import completed. "
                f"Valid: {self.stats['valid_rows']}, "
                f"Invalid: {self.stats['invalid_rows']}, "
                f"Total: {self.stats['total_rows']}"
            )
            
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Error reading JSON file: {e}")
            raise
        
        return valid_data
    
    def get_import_statistics(self) -> Dict[str, Any]:
        """Получение статистики импорта"""
        return self.stats.copy()


# Пример использования
def example_usage() -> None:
    """Пример использования сервиса импорта"""
    
    # Создаем схему данных
    schema = DataSchema()
    
    # Добавляем поля с валидаторами
    schema.add_field(
        "id",
        [RequiredValidator(), IntegerValidator(min_value=1)],
        field_type="integer"
    )
    
    schema.add_field(
        "name",
        [
            RequiredValidator(),
            StringValidator(min_length=2, max_length=100)
        ],
        field_type="string"
    )
    
    schema.add_field(
        "email",
        [RequiredValidator(), EmailValidator()],
        field_type="string"
    )
    
    schema.add_field(
        "age",
        [IntegerValidator(min_value=0, max_value=120)],
        is_required=False,
        field_type="integer"
    )
    
    schema.add_field(
        "salary",
        [DecimalValidator(min_value=Decimal('0'), precision=2)],
        is_required=False,
        field_type="decimal"
    )
    
    schema.add_field(
        "hire_date",
        [DateValidator(date_format="%Y-%m-%d")],
        is_required=False,
        field_type="date"
    )
    
    # Создаем валидатор и импортер
    validator = DataValidator(schema)
    importer = DataImporter(validator)
    
    # Пример CSV данных (в реальном случае читали бы из файла)
    csv_data = """id,name,email,age,salary,hire_date
1,John Doe,john@example.com,30,50000.50,2023-01-15
2,Jane Smith,jane@example.com,25,45000.00,2023-02-20
3,Bob Johnson,bob@example.com,,,2023-03-10
4,Alice Brown,alice@example.com,35,55000.75,
5,,invalid-email,40,60000.00,2023-05-05"""
    
    # Сохраняем пример данных во временный файл
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_data)
        csv_file_path = f.name
    
    try:
        # Импортируем данные из CSV
        valid_data = importer.import_from_csv(csv_file_path)
        
        # Выводим результаты
        logger.info(f"Valid data rows: {len(valid_data)}")
        
        # Показываем статистику
        stats = importer.get_import_statistics()
        logger.info(f"Import statistics: {stats}")
        
        # Сохраняем валидные данные (например, в БД)
        for data in valid_data:
            logger.info(f"Valid row: {data}")
            # Здесь была бы логика сохранения в БД
            
    finally:
        # Удаляем временный файл
        Path(csv_file_path).unlink()


if __name__ == "__main__":
    import tempfile
    example_usage()