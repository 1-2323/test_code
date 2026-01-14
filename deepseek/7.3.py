from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, status, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import secrets
import hashlib
import re

# Инициализация приложения
app = FastAPI(title="Password Reset Service", version="1.0.0")

# Модели данных
class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(..., min_length=64, max_length=256, description="Токен сброса пароля")
    new_password: str = Field(..., min_length=8, max_length=128, description="Новый пароль")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Подтверждение нового пароля")
    
    @validator('new_password')
    def validate_password_strength(cls, v):
        """Валидация сложности пароля"""
        if len(v) < 8:
            raise ValueError('Пароль должен содержать минимум 8 символов')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Пароль должен содержать хотя бы одну заглавную букву')
        if not re.search(r'[a-z]', v):
            raise ValueError('Пароль должен содержать хотя бы одну строчную букву')
        if not re.search(r'\d', v):
            raise ValueError('Пароль должен содержать хотя бы одну цифру')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Пароль должен содержать хотя бы один специальный символ')
        return v
    
    @validator('confirm_password')
    def validate_passwords_match(cls, v, values):
        """Проверка совпадения паролей"""
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Пароли не совпадают')
        return v

class PasswordResetToken(BaseModel):
    token_hash: str
    user_id: int
    email: str
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None
    is_used: bool = False

# Конфигурация
PASSWORD_RESET_CONFIG = {
    'token_length': 64,
    'token_ttl_minutes': 30,  # 30 минут жизни токена
    'max_attempts_per_hour': 5,
    'password_history_count': 5,  # Хранить последние N паролей
    'bcrypt_rounds': 12  # Для hashlib.pbkdf2_hmac имитация
}

# Имитация хранилищ (в реальном проекте заменить на БД)
password_reset_tokens: Dict[str, PasswordResetToken] = {}
fake_users_db = {
    1: {
        "id": 1,
        "email": "user1@example.com",
        "hashed_password": hashlib.sha256("password123!".encode()).hexdigest(),
        "password_history": [],
        "is_active": True,
        "failed_reset_attempts": 0,
        "last_reset_attempt": None
    },
    2: {
        "id": 2,
        "email": "user2@example.com",
        "hashed_password": hashlib.sha256("securepass456!".encode()).hexdigest(),
        "password_history": [],
        "is_active": True,
        "failed_reset_attempts": 0,
        "last_reset_attempt": None
    }
}

# Утилиты для работы с паролями
def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Хеширование пароля с солью"""
    if salt is None:
        salt = secrets.token_hex(16)
    
    # Используем PBKDF2 для более безопасного хеширования
    iterations = 100000
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations
    )
    return f"{salt}:{iterations}:{key.hex()}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля"""
    try:
        salt, iterations, stored_hash = hashed_password.split(':')
        iterations = int(iterations)
        
        key = hashlib.pbkdf2_hmac(
            'sha256',
            plain_password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
        return secrets.compare_digest(key.hex(), stored_hash)
    except (ValueError, AttributeError):
        # Для обратной совместимости с старыми паролями
        old_hash = hashlib.sha256(plain_password.encode()).hexdigest()
        return secrets.compare_digest(old_hash, hashed_password)

def generate_reset_token() -> str:
    """Генерация токена сброса пароля"""
    return secrets.token_urlsafe(PASSWORD_RESET_CONFIG['token_length'])

def hash_token(token: str) -> str:
    """Хеширование токена для безопасного хранения"""
    return hashlib.sha256(token.encode()).hexdigest()

def is_password_in_history(user_id: int, new_password: str) -> bool:
    """Проверка, использовался ли пароль ранее"""
    user = fake_users_db.get(user_id)
    if not user or 'password_history' not in user:
        return False
    
    for old_password_hash in user['password_history']:
        if verify_password(new_password, old_password_hash):
            return True
    return False

def add_password_to_history(user_id: int, password_hash: str):
    """Добавление пароля в историю"""
    user = fake_users_db.get(user_id)
    if user and 'password_history' in user:
        user['password_history'].insert(0, password_hash)
        # Ограничиваем количество хранимых паролей
        if len(user['password_history']) > PASSWORD_RESET_CONFIG['password_history_count']:
            user['password_history'] = user['password_history'][:PASSWORD_RESET_CONFIG['password_history_count']]

def check_rate_limit(user_id: int) -> bool:
    """Проверка ограничения попыток сброса пароля"""
    user = fake_users_db.get(user_id)
    if not user:
        return False
    
    current_time = datetime.now()
    
    # Сбрасываем счетчик, если прошло больше часа
    if user['last_reset_attempt']:
        time_diff = current_time - user['last_reset_attempt']
        if time_diff.total_seconds() > 3600:
            user['failed_reset_attempts'] = 0
    
    # Проверяем лимит
    if user['failed_reset_attempts'] >= PASSWORD_RESET_CONFIG['max_attempts_per_hour']:
        return False
    
    return True

def update_rate_limit(user_id: int, success: bool):
    """Обновление счетчика попыток"""
    user = fake_users_db.get(user_id)
    if user:
        current_time = datetime.now()
        
        if success:
            user['failed_reset_attempts'] = 0
        else:
            user['failed_reset_attempts'] += 1
        
        user['last_reset_attempt'] = current_time

def validate_reset_token(token: str) -> Optional[Dict[str, Any]]:
    """Проверка валидности токена сброса пароля"""
    token_hash = hash_token(token)
    
    # Ищем токен в хранилище
    stored_token = None
    for token_data in password_reset_tokens.values():
        if secrets.compare_digest(token_data.token_hash, token_hash):
            stored_token = token_data
            break
    
    if not stored_token:
        return None
    
    # Проверяем срок действия
    current_time = datetime.now()
    if stored_token.expires_at < current_time:
        # Удаляем просроченный токен
        for key, token_data in list(password_reset_tokens.items()):
            if token_data.token_hash == stored_token.token_hash:
                del password_reset_tokens[key]
                break
        return None
    
    # Проверяем, не использовался ли токен
    if stored_token.is_used:
        return None
    
    return {
        'token_data': stored_token,
        'user_id': stored_token.user_id,
        'email': stored_token.email
    }

def cleanup_expired_tokens():
    """Очистка просроченных токенов"""
    current_time = datetime.now()
    expired_keys = []
    
    for key, token_data in password_reset_tokens.items():
        if token_data.expires_at < current_time:
            expired_keys.append(key)
    
    for key in expired_keys:
        del password_reset_tokens[key]

async def send_password_change_notification(email: str):
    """Отправка уведомления об изменении пароля (заглушка)"""
    # В реальном проекте реализовать отправку email
    print(f"Уведомление отправлено на {email}: Пароль был успешно изменен")
    # Здесь должна быть логика отправки email через SMTP или email сервис

@app.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
async def password_reset_confirm(
    request_data: PasswordResetConfirmRequest,
    background_tasks: BackgroundTasks,
    request: Request
):
    """
    Эндпоинт для подтверждения сброса пароля
    
    Принимает токен сброса пароля и новый пароль,
    проверяет валидность токена и устанавливает новый пароль
    """
    try:
        # Очищаем просроченные токены
        cleanup_expired_tokens()
        
        # Валидируем токен
        token_validation = validate_reset_token(request_data.token)
        if not token_validation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Недействительный или просроченный токен сброса пароля"
            )
        
        user_id = token_validation['user_id']
        email = token_validation['email']
        token_data = token_validation['token_data']
        
        # Проверяем ограничение попыток
        if not check_rate_limit(user_id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много попыток сброса пароля. Попробуйте позже."
            )
        
        # Получаем пользователя
        user = fake_users_db.get(user_id)
        if not user or not user.get('is_active', True):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь не найден или аккаунт заблокирован"
            )
        
        # Проверяем, не использовался ли этот пароль ранее
        if is_password_in_history(user_id, request_data.new_password):
            update_rate_limit(user_id, False)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Этот пароль уже использовался ранее. Выберите другой пароль."
            )
        
        # Хешируем новый пароль
        new_password_hash = hash_password(request_data.new_password)
        
        # Сохраняем старый пароль в историю
        add_password_to_history(user_id, user['hashed_password'])
        
        # Обновляем пароль пользователя
        user['hashed_password'] = new_password_hash
        
        # Помечаем токен как использованный
        token_data.is_used = True
        token_data.used_at = datetime.now()
        
        # Обновляем счетчик попыток
        update_rate_limit(user_id, True)
        
        # Добавляем задачу для отправки уведомления
        background_tasks.add_task(send_password_change_notification, email)
        
        # Формируем ответ
        response_data = {
            "status": "success",
            "message": "Пароль успешно изменен",
            "data": {
                "user_id": user_id,
                "email": email,
                "password_changed_at": datetime.now().isoformat()
            }
        }
        
        # В реальном проекте здесь можно добавить инвалидацию сессий пользователя
        # для обеспечения безопасности
        
        return JSONResponse(content=response_data)
        
    except HTTPException:
        # Перевыбрасываем HTTP исключения
        raise
    except ValueError as e:
        # Обработка ошибок валидации Pydantic
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Логируем внутренние ошибки
        print(f"Ошибка при сбросе пароля: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера при обработке запроса на сброс пароля"
        )

# Вспомогательный эндпоинт для создания токена сброса (для тестирования)
class PasswordResetRequest(BaseModel):
    email: str = Field(..., description="Email пользователя для сброса пароля")

@app.post("/password-reset/request", status_code=status.HTTP_200_OK)
async def password_reset_request(request_data: PasswordResetRequest):
    """Эндпоинт для запроса сброса пароля (для тестирования)"""
    # Ищем пользователя по email
    user = None
    user_id = None
    
    for uid, user_data in fake_users_db.items():
        if user_data.get('email') == request_data.email:
            user = user_data
            user_id = uid
            break
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь с указанным email не найден"
        )
    
    # Генерируем токен
    token = generate_reset_token()
    token_hash = hash_token(token)
    
    # Создаем запись токена
    now = datetime.now()
    expires_at = now + timedelta(minutes=PASSWORD_RESET_CONFIG['token_ttl_minutes'])
    
    reset_token = PasswordResetToken(
        token_hash=token_hash,
        user_id=user_id,
        email=request_data.email,
        created_at=now,
        expires_at=expires_at
    )
    
    # Сохраняем токен
    token_id = f"{user_id}_{int(now.timestamp())}"
    password_reset_tokens[token_id] = reset_token
    
    # В реальном проекте здесь отправляется email с токеном
    print(f"Токен сброса пароля для {request_data.email}: {token}")
    
    return {
        "status": "success",
        "message": "Токен сброса пароля создан",
        "data": {
            "token": token,  # В production не возвращать токен, только отправлять по email
            "expires_at": expires_at.isoformat()
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)