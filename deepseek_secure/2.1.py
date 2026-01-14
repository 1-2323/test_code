from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from datetime import datetime
import re
from typing import Optional

# Инициализация FastAPI
app = FastAPI(title="Authentication System")

# Настройка базы данных (SQLite для примера, в продакшене используйте PostgreSQL/MySQL)
SQLALCHEMY_DATABASE_URL = "sqlite:///./users.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Настройка хеширования паролей с использованием bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Модель пользователя для базы данных
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Pydantic модели для валидации
class UserSignUp(BaseModel):
    email: EmailStr
    password: constr(min_length=8, max_length=100)
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "password": "StrongPass123!"
            }
        }

class UserResponse(BaseModel):
    id: int
    email: str
    is_active: bool
    created_at: datetime

# Вспомогательные функции
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def validate_password_strength(password: str) -> bool:
    """
    Проверка сложности пароля:
    - Минимум 8 символов
    - Минимум одна цифра
    - Минимум одна заглавная буква
    - Минимум одна строчная буква
    - Минимум один специальный символ
    """
    if len(password) < 8:
        return False
    
    checks = [
        r'\d',           # цифры
        r'[A-Z]',        # заглавные буквы
        r'[a-z]',        # строчные буквы
        r'[!@#$%^&*(),.?":{}|<>]'  # специальные символы
    ]
    
    return all(re.search(pattern, password) for pattern in checks)

def get_password_hash(password: str) -> str:
    """Хеширование пароля с использованием bcrypt"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля"""
    return pwd_context.verify(plain_password, hashed_password)

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Поиск пользователя по email"""
    return db.query(User).filter(User.email == email).first()

# Эндпоинт регистрации
@app.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация нового пользователя",
    description="Создание нового пользователя с валидацией email и пароля",
    tags=["Authentication"]
)
async def signup(
    user_data: UserSignUp,
    db: Session = Depends(get_db)
):
    """
    Регистрация пользователя:
    
    - **email**: Действительный email адрес
    - **password**: Пароль (минимум 8 символов, цифры, заглавные и строчные буквы, специальные символы)
    """
    
    # Проверка существования пользователя
    existing_user = get_user_by_email(db, user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже зарегистрирован"
        )
    
    # Валидация сложности пароля
    if not validate_password_strength(user_data.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль недостаточно сложен. Требования: минимум 8 символов, цифры, заглавные и строчные буквы, специальные символы"
        )
    
    try:
        # Хеширование пароля
        hashed_password = get_password_hash(user_data.password)
        
        # Создание нового пользователя
        new_user = User(
            email=user_data.email,
            hashed_password=hashed_password
        )
        
        # Сохранение в базу данных
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        # Возвращаем данные пользователя (без хеша пароля)
        return UserResponse(
            id=new_user.id,
            email=new_user.email,
            is_active=new_user.is_active,
            created_at=new_user.created_at
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Произошла ошибка при регистрации: {str(e)}"
        )