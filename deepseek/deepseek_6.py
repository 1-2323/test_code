"""
Сервис регистрации пользователей с валидацией, хешированием пароля
и сохранением в базу данных.
"""

import re
import bcrypt
from typing import Optional, Tuple
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Настройка базы данных (в реальном проекте вынести в конфиг)
DATABASE_URL = "sqlite:///users.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """Модель пользователя для SQLAlchemy."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"


# Создаем таблицы (в продакшене использовать миграции)
Base.metadata.create_all(bind=engine)


class EmailValidator:
    """Валидатор email адресов."""
    
    @staticmethod
    def validate(email: str) -> bool:
        """
        Проверяет корректность email адреса.
        
        Args:
            email: Строка с email для проверки
            
        Returns:
            True если email корректен, иначе False
        """
        if not email:
            return False
        
        # Простая, но эффективная регулярка для email
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))


class PasswordValidator:
    """Валидатор сложности пароля."""
    
    @staticmethod
    def validate(password: str, min_length: int = 8) -> Tuple[bool, Optional[str]]:
        """
        Проверяет сложность пароля.
        
        Args:
            password: Пароль для проверки
            min_length: Минимальная длина пароля
            
        Returns:
            Кортеж (валиден_ли, сообщение_об_ошибке)
        """
        if len(password) < min_length:
            return False, f"Пароль должен содержать минимум {min_length} символов"
        
        if not any(c.isupper() for c in password):
            return False, "Пароль должен содержать хотя бы одну заглавную букву"
        
        if not any(c.islower() for c in password):
            return False, "Пароль должен содержать хотя бы одну строчную букву"
        
        if not any(c.isdigit() for c in password):
            return False, "Пароль должен содержать хотя бы одну цифру"
        
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            return False, "Пароль должен содержать хотя бы один специальный символ"
        
        return True, None


class PasswordHasher:
    """Сервис для хеширования паролей."""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Создает bcrypt хеш пароля.
        
        Args:
            password: Пароль в виде строки
            
        Returns:
            Хешированный пароль в виде строки
        """
        # Генерируем соль и хешируем пароль
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Проверяет соответствие пароля его хешу.
        
        Args:
            plain_password: Пароль в виде строки
            hashed_password: Хешированный пароль
            
        Returns:
            True если пароль совпадает, иначе False
        """
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )


class UserRegistrationFlow:
    """Основной сервис регистрации пользователей."""
    
    def __init__(self, db_session: Session):
        """
        Инициализация сервиса регистрации.
        
        Args:
            db_session: Сессия SQLAlchemy для работы с БД
        """
        self.db = db_session
        self.email_validator = EmailValidator()
        self.password_validator = PasswordValidator()
        self.password_hasher = PasswordHasher()
    
    def register_user(self, email: str, password: str) -> Tuple[bool, Optional[str], Optional[User]]:
        """
        Регистрирует нового пользователя.
        
        Args:
            email: Email пользователя
            password: Пароль пользователя
            
        Returns:
            Кортеж (успех, сообщение, объект_пользователя)
        """
        # 1. Валидация email
        if not self.email_validator.validate(email):
            return False, "Некорректный email адрес", None
        
        # 2. Проверка сложности пароля
        is_valid, error_message = self.password_validator.validate(password)
        if not is_valid:
            return False, error_message, None
        
        # 3. Проверка уникальности email
        existing_user = self.db.query(User).filter(User.email == email).first()
        if existing_user:
            return False, "Пользователь с таким email уже существует", None
        
        try:
            # 4. Хеширование пароля
            password_hash = self.password_hasher.hash_password(password)
            
            # 5. Создание и сохранение пользователя
            user = User(
                email=email,
                password_hash=password_hash
            )
            
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            
            return True, "Пользователь успешно зарегистрирован", user
            
        except Exception as e:
            self.db.rollback()
            return False, f"Ошибка при регистрации: {str(e)}", None


# Пример использования
if __name__ == "__main__":
    # Создаем сессию БД
    db = SessionLocal()
    
    # Инициализируем сервис регистрации
    registration_service = UserRegistrationFlow(db)
    
    # Регистрируем пользователя
    success, message, user = registration_service.register_user(
        email="user@example.com",
        password="StrongPass123!"
    )
    
    if success:
        print(f"Успех: {message}")
        print(f"Создан пользователь: {user}")
    else:
        print(f"Ошибка: {message}")
    
    # Закрываем сессию
    db.close()