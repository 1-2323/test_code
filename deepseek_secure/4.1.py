import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr, validator
from fastapi import FastAPI, HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import redis.asyncio as redis
import jwt
from email.mime.text import MIMEText
import aiosmtplib

# Конфигурация (должна быть вынесена в переменные окружения)
SECRET_KEY = secrets.token_urlsafe(64)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
MFA_TOKEN_EXPIRE_MINUTES = 10
REDIS_URL = "redis://localhost:6379"
SMTP_CONFIG = {
    "host": "smtp.example.com",
    "port": 587,
    "username": "noreply@example.com",
    "password": "smtp_password",
    "use_tls": True
}

# Инициализация приложения
app = FastAPI(title="Password Recovery API")
security = HTTPBearer()

# Redis клиент для хранения временных данных
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Модели данных
class RecoveryInitRequest(BaseModel):
    """Запрос на инициацию восстановления"""
    email: EmailStr
    device_id: Optional[str] = None
    
    @validator('device_id')
    def validate_device_id(cls, v):
        if v and len(v) > 100:
            raise ValueError('Device ID слишком длинный')
        return v

class MFAVerificationRequest(BaseModel):
    """Запрос на верификацию MFA"""
    recovery_token: str
    mfa_code: str
    
    @validator('mfa_code')
    def validate_mfa_code(cls, v):
        if not v.isdigit() or len(v) != 6:
            raise ValueError('MFA код должен состоять из 6 цифр')
        return v

class PasswordResetRequest(BaseModel):
    """Запрос на сброс пароля"""
    reset_token: str
    new_password: str
    
    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 12:
            raise ValueError('Пароль должен быть не менее 12 символов')
        if not any(c.isupper() for c in v):
            raise ValueError('Пароль должен содержать заглавные буквы')
        if not any(c.islower() for c in v):
            raise ValueError('Пароль должен содержать строчные буквы')
        if not any(c.isdigit() for c in v):
            raise ValueError('Пароль должен содержать цифры')
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
            raise ValueError('Пароль должен содержать специальные символы')
        return v

class RecoverySessionData(BaseModel):
    """Данные сессии восстановления"""
    email: str
    user_id: str
    device_id: Optional[str] = None
    mfa_verified: bool = False
    failed_attempts: int = 0
    created_at: float
    mfa_method: str = "email"

# Утилиты
async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Получение пользователя из БД (заглушка)
    В реальном приложении здесь будет запрос к базе данных
    """
    # Имитация поиска пользователя
    users_db = {
        "user@example.com": {
            "id": "user_123",
            "email": "user@example.com",
            "hashed_password": "old_hash",
            "mfa_enabled": True,
            "backup_codes": ["123456", "654321"]
        }
    }
    return users_db.get(email)

async def update_user_password(user_id: str, new_password_hash: str):
    """
    Обновление пароля пользователя (заглушка)
    """
    # В реальном приложении здесь будет обновление в БД
    print(f"Password updated for user {user_id}")

async def send_mfa_code(email: str, code: str, method: str = "email"):
    """
    Отправка MFA кода пользователю
    """
    if method == "email":
        msg = MIMEText(f"Ваш код для восстановления пароля: {code}\nКод действителен 10 минут.")
        msg["Subject"] = "Код восстановления пароля"
        msg["From"] = SMTP_CONFIG["username"]
        msg["To"] = email
        
        await aiosmtplib.send(
            msg,
            hostname=SMTP_CONFIG["host"],
            port=SMTP_CONFIG["port"],
            username=SMTP_CONFIG["username"],
            password=SMTP_CONFIG["password"],
            use_tls=SMTP_CONFIG["use_tls"]
        )

def generate_mfa_code() -> str:
    """Генерация 6-значного MFA кода"""
    return f"{secrets.randbelow(1000000):06d}"

def create_recovery_token(data: Dict[str, Any]) -> str:
    """Создание JWT токена для восстановления"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_reset_token(data: Dict[str, Any]) -> str:
    """Создание JWT токена для сброса пароля"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=5)  # Короткое время жизни
    to_encode.update({"exp": expire, "type": "password_reset"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def verify_and_decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Верификация и декодирование JWT токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

async def rate_limit_check(email: str, redis_key_prefix: str) -> bool:
    """
    Проверка лимита запросов
    """
    key = f"{redis_key_prefix}:{email}"
    attempts = await redis_client.get(key)
    
    if attempts and int(attempts) >= 5:
        return False
    
    if attempts:
        await redis_client.incr(key)
    else:
        await redis_client.setex(key, 3600, 1)  # 1 час
    
    return True

# Эндпоинты
@app.post("/recover/init", status_code=status.HTTP_200_OK)
async def initiate_recovery(request: RecoveryInitRequest):
    """
    Инициация процесса восстановления пароля с MFA
    """
    # Проверка лимита запросов
    if not await rate_limit_check(request.email, "recovery_init"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много запросов. Попробуйте позже."
        )
    
    # Поиск пользователя
    user = await get_user_by_email(request.email)
    if not user:
        # Не раскрываем информацию о существовании пользователя
        await asyncio.sleep(secrets.randbelow(3) + 1)  # Добавляем задержку
        return {"message": "Если пользователь существует, инструкции отправлены на email"}
    
    # Генерация MFA кода
    mfa_code = generate_mfa_code()
    session_id = secrets.token_urlsafe(32)
    
    # Сохранение сессии в Redis
    session_data = RecoverySessionData(
        email=request.email,
        user_id=user["id"],
        device_id=request.device_id,
        created_at=time.time(),
        mfa_method="email"
    ).dict()
    
    # Сохранение MFA кода с хэшированием
    mfa_hash = hashlib.sha256(mfa_code.encode()).hexdigest()
    await redis_client.hset(f"recovery_session:{session_id}", mapping={
        **session_data,
        "mfa_hash": mfa_hash,
        "mfa_expires": time.time() + MFA_TOKEN_EXPIRE_MINUTES * 60
    })
    await redis_client.expire(f"recovery_session:{session_id}", ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    
    # Отправка MFA кода
    await send_mfa_code(request.email, mfa_code)
    
    # Создание recovery токена (без MFA кода)
    recovery_token = create_recovery_token({
        "session_id": session_id,
        "user_id": user["id"],
        "email": request.email
    })
    
    return {
        "message": "MFA код отправлен на email",
        "recovery_token": recovery_token,
        "mfa_method": "email",
        "expires_in": MFA_TOKEN_EXPIRE_MINUTES * 60
    }

@app.post("/recover/verify-mfa", status_code=status.HTTP_200_OK)
async def verify_mfa(request: MFAVerificationRequest):
    """
    Верификация MFA кода
    """
    # Декодирование токена
    token_data = await verify_and_decode_token(request.recovery_token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный токен"
        )
    
    session_id = token_data.get("session_id")
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат токена"
        )
    
    # Получение сессии из Redis
    session_key = f"recovery_session:{session_id}"
    session_data = await redis_client.hgetall(session_key)
    
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сессия восстановления не найдена"
        )
    
    # Проверка количества попыток
    failed_attempts = int(session_data.get("failed_attempts", 0))
    if failed_attempts >= 3:
        await redis_client.delete(session_key)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Превышено количество попыток. Начните процесс заново."
        )
    
    # Проверка срока действия MFA кода
    mfa_expires = float(session_data.get("mfa_expires", 0))
    if time.time() > mfa_expires:
        await redis_client.hincrby(session_key, "failed_attempts", 1)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Срок действия MFA кода истек"
        )
    
    # Верификация MFA кода
    stored_mfa_hash = session_data.get("mfa_hash")
    provided_mfa_hash = hashlib.sha256(request.mfa_code.encode()).hexdigest()
    
    if not secrets.compare_digest(stored_mfa_hash, provided_mfa_hash):
        await redis_client.hincrby(session_key, "failed_attempts", 1)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный MFA код"
        )
    
    # Обновление сессии
    await redis_client.hset(session_key, "mfa_verified", "true")
    await redis_client.hdel(session_key, "mfa_hash", "mfa_expires")
    
    # Создание токена для сброса пароля
    reset_token = create_reset_token({
        "session_id": session_id,
        "user_id": session_data["user_id"],
        "email": session_data["email"]
    })
    
    return {
        "message": "MFA успешно верифицирован",
        "reset_token": reset_token,
        "expires_in": 300  # 5 минут
    }

@app.post("/recover/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(request: PasswordResetRequest):
    """
    Сброс пароля после успешной MFA верификации
    """
    # Верификация токена сброса
    token_data = await verify_and_decode_token(request.reset_token)
    if not token_data or token_data.get("type") != "password_reset":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный токен сброса"
        )
    
    session_id = token_data.get("session_id")
    user_id = token_data.get("user_id")
    
    if not session_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат токена"
        )
    
    # Проверка сессии
    session_key = f"recovery_session:{session_id}"
    session_data = await redis_client.hgetall(session_key)
    
    if not session_data or session_data.get("mfa_verified") != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуется верификация MFA"
        )
    
    # Хэширование нового пароля
    new_password_hash = hashlib.sha256(request.new_password.encode()).hexdigest()
    
    # Обновление пароля в БД
    await update_user_password(user_id, new_password_hash)
    
    # Удаление сессии и инвалидация всех активных сессий пользователя
    await redis_client.delete(session_key)
    await redis_client.sadd(f"password_changed:{user_id}", str(int(time.time())))
    await redis_client.expire(f"password_changed:{user_id}", 3600)
    
    # Логирование события
    await redis_client.lpush(
        "security_logs:password_reset",
        f"{datetime.utcnow().isoformat()}:{user_id}:{token_data.get('email')}"
    )
    await redis_client.ltrim("security_logs:password_reset", 0, 999)
    
    return {
        "message": "Пароль успешно изменен",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/recover/backup-mfa", status_code=status.HTTP_200_OK)
async def use_backup_code(request: MFAVerificationRequest):
    """
    Использование резервного кода вместо MFA
    """
    # Аналогично /recover/verify-mfa, но с проверкой резервных кодов
    # Реализация зависит от системы хранения резервных кодов
    pass

# Зависимости для защиты других эндпоинтов
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Зависимость для получения текущего пользователя
    с проверкой смены пароля
    """
    token = credentials.credentials
    payload = await verify_and_decode_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительные учетные данные"
        )
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный формат токена"
        )
    
    # Проверка, не был ли пароль изменен после выдачи токена
    token_iat = payload.get("iat")
    if token_iat:
        password_changes = await redis_client.smembers(f"password_changed:{user_id}")
        for change_time in password_changes:
            if int(change_time) > token_iat:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Пароль был изменен. Требуется повторная авторизация."
                )
    
    return payload

# Middleware для дополнительной безопасности
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# Запуск приложения
if __name__ == "__main__":
    import uvicorn
    import asyncio
    
    async def init_redis():
        await redis_client.ping()
    
    asyncio.run(init_redis())
    uvicorn.run(app, host="0.0.0.0", port=8000)