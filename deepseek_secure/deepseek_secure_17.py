from typing import Any, Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime, date
import re
from email_validator import validate_email, EmailNotValidError
import phonenumbers
from abc import ABC, abstractmethod

class ValidationError(Exception):
    """Ошибка валидации."""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")

@dataclass
class ValidationRule:
    """Правило валидации."""
    field: str
    validators: List[Callable]
    required: bool = True
    error_message: Optional[str] = None

class Validator(ABC):
    """Базовый класс валидатора."""
    
    @abstractmethod
    def validate(self, value: Any) -> Tuple[bool, str]:
        pass

class RequiredValidator(Validator):
    """Валидатор обязательного поля."""
    
    def validate(self, value: Any) -> Tuple[bool, str]:
        if value is None or (isinstance(value, str) and not value.strip()):
            return False, "Field is required"
        return True, ""

class EmailValidator(Validator):
    """Валидатор email."""
    
    def validate(self, value: Any) -> Tuple[bool, str]:
        if not value:
            return True, ""  # Не required
        
        try:
            validate_email(value, check_deliverability=False)
            return True, ""
        except EmailNotValidError as e:
            return False, str(e)

class PhoneValidator(Validator):
    """Валидатор телефона."""
    
    def __init__(self, region: str = "RU"):
        self.region = region
    
    def validate(self, value: Any) -> Tuple[bool, str]:
        if not value:
            return True, ""
        
        try:
            parsed = phonenumbers.parse(value, self.region)
            if not phonenumbers.is_valid_number(parsed):
                return False, "Invalid phone number"
            return True, ""
        except Exception:
            return False, "Invalid phone format"

class LengthValidator(Validator):
    """Валидатор длины."""
    
    def __init__(self, min_length: Optional[int] = None, 
                 max_length: Optional[int] = None):
        self.min_length = min_length
        self.max_length = max_length
    
    def validate(self, value: Any) -> Tuple[bool, str]:
        if not value:
            return True, ""
        
        if not isinstance(value, str):
            value = str(value)
        
        length = len(value)
        
        if self.min_length and length < self.min_length:
            return False, f"Minimum length is {self.min_length}"
        
        if self.max_length and length > self.max_length:
            return False, f"Maximum length is {self.max_length}"
        
        return True, ""

class RegexValidator(Validator):
    """Валидатор по регулярному выражению."""
    
    def __init__(self, pattern: str, error_msg: str = "Invalid format"):
        self.pattern = re.compile(pattern)
        self.error_msg = error_msg
    
    def validate(self, value: Any) -> Tuple[bool, str]:
        if not value:
            return True, ""
        
        if not isinstance(value, str):
            value = str(value)
        
        if not self.pattern.match(value):
            return False, self.error_msg
        
        return True, ""

class NumberRangeValidator(Validator):
    """Валидатор диапазона чисел."""
    
    def __init__(self, min_val: Optional[float] = None,
                 max_val: Optional[float] = None):
        self.min_val = min_val
        self.max_val = max_val
    
    def validate(self, value: Any) -> Tuple[bool, str]:
        if value is None:
            return True, ""
        
        try:
            num = float(value) if not isinstance(value, (int, float)) else value
        except ValueError:
            return False, "Must be a number"
        
        if self.min_val is not None and num < self.min_val:
            return False, f"Minimum value is {self.min_val}"
        
        if self.max_val is not None and num > self.max_val:
            return False, f"Maximum value is {self.max_val}"
        
        return True, ""

class DateValidator(Validator):
    """Валидатор даты."""
    
    def __init__(self, format: str = "%Y-%m-%d", 
                 min_date: Optional[date] = None,
                 max_date: Optional[date] = None):
        self.format = format
        self.min_date = min_date
        self.max_date = max_date
    
    def validate(self, value: Any) -> Tuple[bool, str]:
        if not value:
            return True, ""
        
        if isinstance(value, (datetime, date)):
            dt = value.date() if isinstance(value, datetime) else value
        else:
            try:
                dt = datetime.strptime(str(value), self.format).date()
            except ValueError:
                return False, f"Date must be in format {self.format}"
        
        if self.min_date and dt < self.min_date:
            return False, f"Date must be after {self.min_date}"
        
        if self.max_date and dt > self.max_date:
            return False, f"Date must be before {self.max_date}"
        
        return True, ""

class CustomValidator(Validator):
    """Кастомный валидатор."""
    
    def __init__(self, validation_func: Callable[[Any], bool],
                 error_msg: str = "Validation failed"):
        self.validation_func = validation_func
        self.error_msg = error_msg
    
    def validate(self, value: Any) -> Tuple[bool, str]:
        try:
            if self.validation_func(value):
                return True, ""
            return False, self.error_msg
        except Exception as e:
            return False, f"Validation error: {str(e)}"

class ValidationSchema:
    """Схема валидации."""
    
    def __init__(self):
        self.rules: Dict[str, ValidationRule] = {}
    
    def add_rule(self, field: str, *validators: Validator,
                 required: bool = True,
                 error_message: Optional[str] = None):
        """Добавление правила валидации."""
        self.rules[field] = ValidationRule(
            field=field,
            validators=list(validators),
            required=required,
            error_message=error_message
        )
    
    def validate(self, data: Dict[str, Any]) -> Dict[str, List[str]]:
        """Валидация данных."""
        errors = {}
        
        for field, rule in self.rules.items():
            value = data.get(field)
            field_errors = []
            
            # Проверка обязательного поля
            if rule.required and (value is None or 
                (isinstance(value, str) and not value.strip())):
                field_errors.append(rule.error_message or "Field is required")
                continue
            
            # Если поле не required и пустое - пропускаем
            if not rule.required and not value:
                continue
            
            # Проверка валидаторами
            for validator in rule.validators:
                is_valid, error_msg = validator.validate(value)
                if not is_valid:
                    field_errors.append(error_msg)
            
            if field_errors:
                errors[field] = field_errors
        
        return errors
    
    def is_valid(self, data: Dict[str, Any]) -> bool:
        """Проверка валидности данных."""
        return len(self.validate(data)) == 0

class DataValidator:
    """Основной валидатор данных."""
    
    def __init__(self):
        self.schemas: Dict[str, ValidationSchema] = {}
    
    def register_schema(self, name: str, schema: ValidationSchema):
        """Регистрация схемы валидации."""
        self.schemas[name] = schema
    
    def validate(self, schema_name: str, data: Dict[str, Any]) -> Dict[str, List[str]]:
        """Валидация данных по схеме."""
        if schema_name not in self.schemas:
            raise ValueError(f"Schema '{schema_name}' not found")
        
        return self.schemas[schema_name].validate(data)
    
    @staticmethod
    def create_user_registration_schema() -> ValidationSchema:
        """Создание схемы для регистрации пользователя."""
        schema = ValidationSchema()
        
        schema.add_rule(
            "email",
            RequiredValidator(),
            EmailValidator(),
            error_message="Valid email is required"
        )
        
        schema.add_rule(
            "password",
            RequiredValidator(),
            LengthValidator(min_length=8, max_length=100),
            RegexValidator(
                pattern=r'^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$',
                error_msg="Password must contain uppercase, lowercase, number and special character"
            )
        )
        
        schema.add_rule(
            "username",
            RequiredValidator(),
            LengthValidator(min_length=3, max_length=50),
            RegexValidator(
                pattern=r'^[a-zA-Z0-9_]+$',
                error_msg="Username can only contain letters, numbers and underscores"
            )
        )
        
        schema.add_rule(
            "phone",
            PhoneValidator(region="RU"),
            required=False
        )
        
        schema.add_rule(
            "age",
            NumberRangeValidator(min_val=18, max_val=120),
            required=False
        )
        
        return schema