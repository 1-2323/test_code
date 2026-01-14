import secrets
import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, validator
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError
import aioredis
import aiosmtplib
from email.message import EmailMessage
import configparser
import logging

# Конфигурация
config = configparser.ConfigParser()
config.read('config.ini')

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI приложение
app = FastAPI(title="Password Reset API")

# База данных
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Модели Pydantic
class PasswordResetRequest(BaseModel):
    email: EmailStr
    
    @validator('email')
    def email_to_lowercase(cls, v):
        return v.lower()

class PasswordResetResponse(BaseModel):
    message: str
    expires_in_minutes: int

# Зависимости
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_redis():
    redis = await aioredis.from_url(
        config.get('redis', 'url'),
        encoding="utf-8",
        decode_responses=True
    )
    try:
        yield redis
    finally:
        await redis.close()

# Инициализация базы данных
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = config.get('database', 'url')
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

# Конфигурационные константы
TOKEN_BYTES = 32
TOKEN_EXPIRY_MINUTES = 15
RATE_LIMIT_WINDOW = 300  # 5 минут в секундах
RATE_LIMIT_MAX_REQUESTS = 3

# Вспомогательные функции
def hash_token(token: str) -> str:
    """Хеширование токена для безопасного хранения"""
    salt = config.get('security', 'token_salt', fallback='default_salt_change_in_production')
    return hashlib.sha256(f"{token}{salt}".encode()).hexdigest()

def generate_secure_token() -> str:
    """Генерация криптографически стойкого токена"""
    return secrets.token_urlsafe(TOKEN_BYTES)

async def check_rate_limit(email: str, redis: aioredis.Redis) -> bool:
    """Проверка лимита запросов для email"""
    key = f"pwd_reset:{email}"
    current = await redis.get(key)
    
    if current is None:
        await redis.setex(key, RATE_LIMIT_WINDOW, "1")
        return True
    
    if int(current) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    
    await redis.incr(key)
    return True

async def send_reset_email(email: str, token: str):
    """Отправка email с ссылкой для сброса пароля"""
    reset_url = f"{config.get('frontend', 'base_url')}/reset-password?token={token}"
    expiry_minutes = TOKEN_EXPIRY_MINUTES
    
    message = EmailMessage()
    message["From"] = config.get('email', 'sender')
    message["To"] = email
    message["Subject"] = "Сброс пароля"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body>
        <h2>Сброс пароля</h2>
        <p>Для сброса пароля перейдите по ссылке:</p>
        <p><a href="{reset_url}">{reset_url}</a></p>
        <p>Ссылка действительна {expiry_minutes} минут.</p>
        <p>Если вы не запрашивали сброс пароля, проигнорируйте это письмо.</p>
    </body>
    </html>
    """
    
    message.set_content(html_content, subtype="html")
    
    try:
        await aiosmtplib.send(
            message,
            hostname=config.get('email', 'smtp_host'),
            port=config.getint('email', 'smtp_port'),
            username=config.get('email', 'smtp_user'),
            password=config.get('email', 'smtp_password'),
            use_tls=config.getboolean('email', 'use_tls')
        )
        logger.info(f"Password reset email sent to {email}")
    except Exception as e:
        logger.error(f"Failed to send email to {email}: {str(e)}")
        raise

# Основной эндпоинт
@app.post(
    "/password-reset/request",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Запрос сброса пароля",
    description="Принимает email, генерирует безопасный токен и отправляет ссылку для сброса пароля",
    responses={
        200: {"description": "Ссылка для сброса пароля отправлена на email"},
        400: {"description": "Некорректный запрос или email не найден"},
        429: {"description": "Слишком много запросов. Попробуйте позже"},
        500: {"description": "Внутренняя ошибка сервера"}
    }
)
async def request_password_reset(
    request: PasswordResetRequest,
    db: Session = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis)
):
    """
    Обрабатывает запрос на сброс пароля.
    
    1. Проверяет лимит запросов для email
    2. Проверяет существование пользователя
    3. Генерирует криптографически стойкий токен
    4. Сохраняет хеш токена в базе
    5. Отправляет email с ссылкой
    """
    
    # Проверка лимита запросов
    if not await check_rate_limit(request.email, redis):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много запросов. Пожалуйста, попробуйте позже."
        )
    
    try:
        # Поиск пользователя
        user = db.query(User).filter(
            User.email == request.email,
            User.is_active == True
        ).first()
        
        # Всегда возвращаем успех, даже если пользователь не найден
        # для предотвращения утечки информации (security through obscurity)
        if not user:
            logger.warning(f"Password reset requested for non-existent email: {request.email}")
            return PasswordResetResponse(
                message="Если email зарегистрирован, на него будет отправлена ссылка для сброса пароля",
                expires_in_minutes=TOKEN_EXPIRY_MINUTES
            )
        
        # Отзываем предыдущие неиспользованные токены
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.is_used == False,
            PasswordResetToken.expires_at > datetime.utcnow()
        ).update({"is_used": True})
        
        # Генерация нового токена
        raw_token = generate_secure_token()
        token_hash = hash_token(raw_token)
        
        # Создание записи токена
        expires_at = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
        
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            is_used=False
        )
        
        db.add(reset_token)
        db.commit()
        
        # Отправка email
        await send_reset_email(request.email, raw_token)
        
        logger.info(f"Password reset token created for user {user.id}")
        
        return PasswordResetResponse(
            message="Если email зарегистрирован, на него будет отправлена ссылка для сброса пароля",
            expires_in_minutes=TOKEN_EXPIRY_MINUTES
        )
        
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error during password reset: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )
    except Exception as e:
        logger.error(f"Unexpected error during password reset: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )

# Дополнительный эндпоинт для проверки валидности токена (опционально)
@app.get("/password-reset/validate/{token}")
async def validate_reset_token(token: str, db: Session = Depends(get_db)):
    """Валидация токена сброса пароля"""
    token_hash = hash_token(token)
    
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.is_used == False,
        PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Недействительная или просроченная ссылка"
        )
    
    return {"valid": True, "user_id": reset_token.user_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.get('server', 'host', fallback='0.0.0.0'),
        port=config.getint('server', 'port', fallback=8000)
    )