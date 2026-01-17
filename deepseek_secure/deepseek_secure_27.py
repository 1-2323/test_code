from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, validator
import re
from datetime import date

class FormValidator:
    """Валидатор форм."""
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Валидация email."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Валидация телефона."""
        pattern = r'^\+?[0-9]{10,15}$'
        return bool(re.match(pattern, phone))
    
    @staticmethod
    def validate_password(password: str) -> List[str]:
        """Валидация пароля."""
        errors = []
        if len(password) < 8:
            errors.append("Password must be at least 8 characters")
        if not re.search(r'[A-Z]', password):
            errors.append("Password must contain uppercase letter")
        if not re.search(r'[a-z]', password):
            errors.append("Password must contain lowercase letter")
        if not re.search(r'\d', password):
            errors.append("Password must contain number")
        return errors
    
    @staticmethod
    def validate_date(date_str: str, format: str = "%Y-%m-%d") -> bool:
        """Валидация даты."""
        try:
            datetime.strptime(date_str, format)
            return True
        except ValueError:
            return False

class RegistrationForm(BaseModel):
    """Форма регистрации."""
    email: str = Field(..., description="Email пользователя")
    password: str = Field(..., min_length=8, description="Пароль")
    confirm_password: str = Field(..., description="Подтверждение пароля")
    username: str = Field(..., min_length=3, max_length=50)
    birth_date: Optional[str] = None
    phone: Optional[str] = None
    
    @validator('email')
    def validate_email(cls, v):
        if not FormValidator.validate_email(v):
            raise ValueError('Invalid email format')
        return v
    
    @validator('password')
    def validate_password_strength(cls, v):
        errors = FormValidator.validate_password(v)
        if errors:
            raise ValueError('; '.join(errors))
        return v
    
    @validator('confirm_password')
    def validate_password_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Passwords do not match')
        return v
    
    @validator('username')
    def validate_username(cls, v):
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username can only contain letters, numbers and underscores')
        return v
    
    @validator('phone')
    def validate_phone(cls, v):
        if v and not FormValidator.validate_phone(v):
            raise ValueError('Invalid phone number')
        return v
    
    @validator('birth_date')
    def validate_birth_date(cls, v):
        if v and not FormValidator.validate_date(v):
            raise ValueError('Invalid date format (YYYY-MM-DD)')
        return v