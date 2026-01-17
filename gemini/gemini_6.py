import re
import hashlib
import os
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Инициализация SQLAlchemy
Base = declarative_base()

class User(Base):
    """Модель пользователя для базы данных."""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    salt = Column(String, nullable=False)

class PasswordHasher:
    """Отвечает за безопасное хеширование и проверку паролей."""
    
    @staticmethod
    def hash_password(password: str) -> tuple[str, str]:
        """Генерирует соль и хеширует пароль с использованием PBKDF2."""
        salt = os.urandom(32).hex()
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256', 
            password.encode('utf-8'), 
            salt.encode('utf-8'), 
            100000
        ).hex()
        return pwd_hash, salt

class Validator:
    """Набор методов для валидации данных пользователя."""
    
    @staticmethod
    def is_valid_email(email: str) -> bool:
        """Простая проверка формата email через регулярное выражение."""
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        return bool(re.match(email_regex, email))

    @staticmethod
    def is_strong_password(password: str) -> bool:
        """
        Проверяет сложность пароля:
        - Минимум 8 символов
        - Наличие цифры
        - Наличие заглавной буквы
        """
        if len(password) < 8:
            return False
        if not any(char.isdigit() for char in password):
            return False
        if not any(char.isupper() for char in password):
            return False
        return True

class UserRegistrationFlow:
    """Основной сервис, управляющий процессом регистрации пользователя."""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.hasher = PasswordHasher()
        self.validator = Validator()

    def register(self, email: str, password: str) -> Optional[User]:
        """
        Выполняет полный цикл регистрации:
        1. Валидация входных данных
        2. Проверка существования пользователя
        3. Хеширование пароля
        4. Сохранение в БД
        """
        # 1. Валидация
        if not self.validator.is_valid_email(email):
            raise ValueError("Некорректный формат email.")
        
        if not self.validator.is_strong_password(password):
            raise ValueError("Пароль слишком слабый. Нужно: 8+ симв., цифра, заглавная буква.")

        # 2. Проверка уникальности
        existing_user = self.db.query(User).filter(User.email == email).first()
        if existing_user:
            raise ValueError("Пользователь с таким email уже существует.")

        # 3. Хеширование
        pwd_hash, salt = self.hasher.hash_password(password)

        # 4. Создание и сохранение объекта
        new_user = User(email=email, password_hash=pwd_hash, salt=salt)
        
        try:
            self.db.add(new_user)
            self.db.commit()
            self.db.refresh(new_user)
            print(f"Пользователь {email} успешно зарегистрирован.")
            return new_user
        except Exception as e:
            self.db.rollback()
            raise RuntimeError(f"Ошибка при сохранении в базу данных: {e}")

# --- Пример использования ---
if __name__ == "__main__":
    # Настройка временной БД в памяти
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        flow = UserRegistrationFlow(session)
        try:
            user = flow.register("test@example.com", "SafePass123")
        except ValueError as e:
            print(f"Ошибка регистрации: {e}")