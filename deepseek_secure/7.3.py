import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from pydantic import BaseModel, Field, validator
import jwt
from jwt.exceptions import InvalidTokenError

# Конфигурация
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Модели данных
class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(..., min_length=1, description="Токен для сброса пароля")
    new_password: str = Field(..., min_length=8, description="Новый пароль")
    
    @validator('new_password')
    def validate_password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Пароль должен содержать минимум 8 символов')
        if not any(c.isupper() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну заглавную букву')
        if not any(c.islower() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну строчную букву')
        if not any(c.isdigit() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну цифру')
        return v

class PasswordResetConfirmResponse(BaseModel):
    message: str

# Зависимости
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
router = APIRouter()

# Хранилище для неиспользованных токенов (в production используйте Redis или БД)
blacklisted_tokens = set()

# Функции для работы с паролями
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Хеширование пароля"""
    return pwd_context.hash(password)

# Функции для работы с токенами
def create_password_reset_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Создание JWT токена для сброса пароля"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "type": "password_reset",
        "jti": os.urandom(16).hex()  # Уникальный идентификатор токена
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_password_reset_token(token: str) -> Optional[dict]:
    """Декодирование и валидация токена"""
    try:
        # Проверка на черный список
        if token in blacklisted_tokens:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Токен уже был использован"
            )
            
        payload = jwt.decode(
            token, 
            SECRET_KEY, 
            algorithms=[ALGORITHM],
            options={"require": ["exp", "type", "jti", "sub"]}
        )
        
        # Проверка типа токена
        if payload.get("type") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный тип токена"
            )
            
        return payload
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Срок действия токена истек"
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неверный токен: {str(e)}"
        )

def add_token_to_blacklist(token: str):
    """Добавление токена в черный список"""
    blacklisted_tokens.add(token)
    # В production: сохранять в Redis/БД с TTL

# Функция для обновления пароля в БД (заглушка, нужно реализовать под вашу БД)
async def update_user_password(user_id: str, new_hashed_password: str) -> bool:
    """
    Обновление пароля пользователя в базе данных.
    Возвращает True при успешном обновлении.
    """
    # TODO: Реализовать обновление пароля в вашей базе данных
    # Пример для SQLAlchemy:
    # user = await db.get(User, user_id)
    # if not user:
    #     return False
    # user.hashed_password = new_hashed_password
    # await db.commit()
    return True

# Эндпоинт
@router.post(
    "/password-reset/confirm",
    response_model=PasswordResetConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="Подтверждение сброса пароля",
    description="""
    Эндпоинт для подтверждения сброса пароля по токену.
    
    Требования к паролю:
    - Минимум 8 символов
    - Хотя бы одна заглавная буква
    - Хотя бы одна строчная буква
    - Хотя бы одна цифра
    
    Токен действителен 30 минут и может быть использован только один раз.
    """
)
async def password_reset_confirm(request: PasswordResetConfirmRequest):
    """
    Подтверждение сброса пароля
    
    Args:
        request: Объект с токеном и новым паролем
    
    Returns:
        Сообщение об успешном сбросе пароля
    
    Raises:
        HTTPException: При невалидном токене или ошибке обновления пароля
    """
    # Декодирование и валидация токена
    payload = decode_password_reset_token(request.token)
    
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный токен: отсутствует идентификатор пользователя"
        )
    
    user_id = payload["sub"]
    token_jti = payload.get("jti")
    
    # Хеширование нового пароля
    hashed_password = get_password_hash(request.new_password)
    
    # Обновление пароля в базе данных
    success = await update_user_password(user_id, hashed_password)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    # Добавление токена в черный список
    add_token_to_blacklist(request.token)
    
    # Логирование события (в production)
    print(f"Пароль сброшен для пользователя {user_id}, токен: {token_jti}")
    
    return PasswordResetConfirmResponse(
        message="Пароль успешно изменен"
    )

# Функция для создания токена сброса пароля (для другого эндпоинта)
async def create_and_send_password_reset_token(email: str) -> str:
    """
    Создание и отправка токена сброса пароля
    
    Args:
        email: Email пользователя
    
    Returns:
        Токен для сброса пароля
    """
    # TODO: Проверить, что пользователь с таким email существует
    
    # Создание токена
    token_data = {"sub": email}  # или user_id
    reset_token = create_password_reset_token(token_data)
    
    # TODO: Отправить токен по email
    # Пример:
    # reset_link = f"https://yourapp.com/password-reset/confirm?token={reset_token}"
    # send_reset_email(email, reset_link)
    
    return reset_token