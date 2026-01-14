from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import secrets
import hashlib
import pyotp
import qrcode
import base64
from io import BytesIO

# Инициализация приложения
app = FastAPI(title="2FA Service", version="1.0.0")

# Модели данных
class TwoFactorVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8, description="Одноразовый код 2FA")
    temp_token: Optional[str] = Field(None, description="Временный токен для аутентификации (если есть)")

class TwoFactorSetupResponse(BaseModel):
    secret: str
    qr_code: str
    backup_codes: list[str]

class TwoFactorStatus(BaseModel):
    is_enabled: bool
    setup_date: Optional[datetime]
    last_used: Optional[datetime]

# Конфигурация
TWO_FACTOR_CONFIG = {
    'token_length': 32,
    'temp_token_ttl_minutes': 5,
    'max_attempts': 3,
    'backup_codes_count': 10,
    'backup_code_length': 12,
    'session_duration_hours': 24
}

# Имитация хранилищ (в реальном проекте заменить на БД)
two_factor_secrets: Dict[int, Dict[str, Any]] = {}
temp_auth_tokens: Dict[str, Dict[str, Any]] = {}
sessions_storage: Dict[str, Dict[str, Any]] = {}

# Хранилище пользователей
fake_users_db = {
    1: {
        "id": 1,
        "username": "user1",
        "email": "user1@example.com",
        "hashed_password": hashlib.sha256("password123!".encode()).hexdigest(),
        "is_active": True,
        "two_fa_enabled": False,
        "two_fa_secret": None,
        "two_fa_backup_codes": [],
        "two_fa_setup_date": None,
        "failed_2fa_attempts": 0,
        "last_2fa_attempt": None
    },
    2: {
        "id": 2,
        "username": "user2",
        "email": "user2@example.com",
        "hashed_password": hashlib.sha256("securepass456!".encode()).hexdigest(),
        "is_active": True,
        "two_fa_enabled": True,
        "two_fa_secret": "JBSWY3DPEHPK3PXP",  # Пример секрета
        "two_fa_backup_codes": ["BACKUP123456", "BACKUP789012"],
        "two_fa_setup_date": datetime.now() - timedelta(days=30),
        "failed_2fa_attempts": 0,
        "last_2fa_attempt": None
    }
}

security = HTTPBearer()

# Утилиты для работы с 2FA
def generate_totp_secret() -> str:
    """Генерация секрета для TOTP"""
    return pyotp.random_base32()

def generate_backup_codes(count: int = TWO_FACTOR_CONFIG['backup_codes_count'], 
                         length: int = TWO_FACTOR_CONFIG['backup_code_length']) -> list[str]:
    """Генерация резервных кодов"""
    codes = []
    for _ in range(count):
        # Генерируем читаемый код с дефисами
        code = secrets.token_urlsafe(length)[:length].upper()
        code = '-'.join([code[i:i+4] for i in range(0, len(code), 4)])
        codes.append(code)
    return codes

def hash_backup_code(code: str) -> str:
    """Хеширование резервного кода для безопасного хранения"""
    return hashlib.sha256(code.encode()).hexdigest()

def verify_backup_code(input_code: str, hashed_codes: list[str]) -> bool:
    """Проверка резервного кода"""
    for hashed_code in hashed_codes:
        if secrets.compare_digest(hash_backup_code(input_code), hashed_code):
            return True
    return False

def generate_qr_code(secret: str, username: str, issuer: str = "MyApp") -> str:
    """Генерация QR-кода для настройки 2FA"""
    # Создаем TOTP URI
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=username, issuer_name=issuer)
    
    # Генерируем QR-код
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    
    # Создаем изображение
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Конвертируем в base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return f"data:image/png;base64,{img_str}"

def verify_totp_code(secret: str, code: str) -> bool:
    """Проверка TOTP кода"""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)  # valid_window=1 позволяет небольшое расхождение по времени

def generate_temp_token(user_id: int, purpose: str = "2fa_verification") -> str:
    """Генерация временного токена для 2FA"""
    token = secrets.token_urlsafe(TWO_FACTOR_CONFIG['token_length'])
    now = datetime.now()
    expires_at = now + timedelta(minutes=TWO_FACTOR_CONFIG['temp_token_ttl_minutes'])
    
    temp_auth_tokens[token] = {
        'user_id': user_id,
        'purpose': purpose,
        'created_at': now,
        'expires_at': expires_at,
        'attempts': 0
    }
    
    return token

def validate_temp_token(token: str) -> Optional[Dict[str, Any]]:
    """Проверка валидности временного токена"""
    token_data = temp_auth_tokens.get(token)
    if not token_data:
        return None
    
    # Проверяем срок действия
    if datetime.now() > token_data['expires_at']:
        del temp_auth_tokens[token]
        return None
    
    # Проверяем количество попыток
    if token_data['attempts'] >= TWO_FACTOR_CONFIG['max_attempts']:
        del temp_auth_tokens[token]
        return None
    
    return token_data

def increment_temp_token_attempts(token: str):
    """Увеличение счетчика попыток для временного токена"""
    if token in temp_auth_tokens:
        temp_auth_tokens[token]['attempts'] += 1

def cleanup_expired_temp_tokens():
    """Очистка просроченных временных токенов"""
    now = datetime.now()
    expired_tokens = [
        token for token, data in temp_auth_tokens.items()
        if data['expires_at'] < now
    ]
    
    for token in expired_tokens:
        del temp_auth_tokens[token]

def check_2fa_rate_limit(user_id: int) -> Tuple[bool, Optional[str]]:
    """Проверка ограничения попыток 2FA"""
    user = fake_users_db.get(user_id)
    if not user:
        return False, "Пользователь не найден"
    
    current_time = datetime.now()
    
    # Сбрасываем счетчик, если прошло больше часа
    if user['last_2fa_attempt']:
        time_diff = current_time - user['last_2fa_attempt']
        if time_diff.total_seconds() > 3600:
            user['failed_2fa_attempts'] = 0
    
    # Проверяем лимит
    if user['failed_2fa_attempts'] >= TWO_FACTOR_CONFIG['max_attempts']:
        return False, "Слишком много неудачных попыток. Попробуйте позже."
    
    return True, None

def update_2fa_rate_limit(user_id: int, success: bool):
    """Обновление счетчика попыток 2FA"""
    user = fake_users_db.get(user_id)
    if user:
        current_time = datetime.now()
        
        if success:
            user['failed_2fa_attempts'] = 0
        else:
            user['failed_2fa_attempts'] += 1
        
        user['last_2fa_attempt'] = current_time

def create_session(user_data: Dict[str, Any]) -> Dict[str, Any]:
    """Создание сессии после успешной 2FA"""
    session_token = secrets.token_urlsafe(TWO_FACTOR_CONFIG['token_length'])
    now = datetime.now()
    expires_at = now + timedelta(hours=TWO_FACTOR_CONFIG['session_duration_hours'])
    
    session_data = {
        'user_id': user_data['id'],
        'username': user_data['username'],
        'email': user_data['email'],
        'created_at': now,
        'expires_at': expires_at,
        'two_fa_verified': True,
        'two_fa_verified_at': now
    }
    
    sessions_storage[session_token] = session_data
    
    return {
        'session_token': session_token,
        'session_data': session_data
    }

# Эндпоинт для верификации 2FA
@app.post("/2fa/verify", status_code=status.HTTP_200_OK)
async def two_factor_verify(
    request_data: TwoFactorVerifyRequest,
    request: Request
):
    """
    Эндпоинт для верификации двухфакторной аутентификации
    
    Принимает одноразовый код (TOTP или резервный код) и временный токен,
    проверяет код и завершает вход при успехе
    """
    try:
        # Очищаем просроченные токены
        cleanup_expired_temp_tokens()
        
        # Получаем временный токен из запроса или заголовков
        temp_token = request_data.temp_token
        if not temp_token:
            # Пробуем получить из заголовка Authorization
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("TempToken "):
                temp_token = auth_header.replace("TempToken ", "")
        
        if not temp_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Требуется временный токен аутентификации"
            )
        
        # Валидируем временный токен
        token_data = validate_temp_token(temp_token)
        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Недействительный или просроченный временный токен"
            )
        
        user_id = token_data['user_id']
        
        # Проверяем ограничение попыток
        rate_limit_ok, rate_limit_message = check_2fa_rate_limit(user_id)
        if not rate_limit_ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=rate_limit_message
            )
        
        # Получаем пользователя
        user = fake_users_db.get(user_id)
        if not user or not user.get('is_active', True):
            increment_temp_token_attempts(temp_token)
            update_2fa_rate_limit(user_id, False)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь не найден или аккаунт заблокирован"
            )
        
        # Проверяем, включена ли 2FA у пользователя
        if not user.get('two_fa_enabled', False):
            increment_temp_token_attempts(temp_token)
            update_2fa_rate_limit(user_id, False)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Двухфакторная аутентификация не включена для этого аккаунта"
            )
        
        # Получаем секрет 2FA
        secret = user.get('two_fa_secret')
        if not secret:
            increment_temp_token_attempts(temp_token)
            update_2fa_rate_limit(user_id, False)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Секрет 2FA не настроен"
            )
        
        code = request_data.code.strip()
        is_backup_code = len(code) > 8  # Резервные коды обычно длиннее
        
        code_valid = False
        
        if is_backup_code:
            # Проверяем резервный код
            hashed_backup_codes = user.get('two_fa_backup_codes', [])
            if verify_backup_code(code, hashed_backup_codes):
                code_valid = True
                # Удаляем использованный резервный код
                for i, hashed_code in enumerate(hashed_backup_codes):
                    if secrets.compare_digest(hash_backup_code(code), hashed_code):
                        hashed_backup_codes.pop(i)
                        user['two_fa_backup_codes'] = hashed_backup_codes
                        break
        else:
            # Проверяем TOTP код
            code_valid = verify_totp_code(secret, code)
        
        if not code_valid:
            # Увеличиваем счетчики попыток
            increment_temp_token_attempts(temp_token)
            update_2fa_rate_limit(user_id, False)
            
            # Удаляем временный токен при превышении попыток
            if token_data['attempts'] + 1 >= TWO_FACTOR_CONFIG['max_attempts']:
                del temp_auth_tokens[temp_token]
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неверный код. Слишком много попыток, токен аннулирован."
                )
            
            remaining_attempts = TWO_FACTOR_CONFIG['max_attempts'] - (token_data['attempts'] + 1)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный код. Осталось попыток: {remaining_attempts}"
            )
        
        # Код верный - завершаем аутентификацию
        update_2fa_rate_limit(user_id, True)
        
        # Удаляем использованный временный токен
        if temp_token in temp_auth_tokens:
            del temp_auth_tokens[temp_token]
        
        # Создаем сессию
        session_info = create_session(user)
        
        # Обновляем время последней успешной 2FA
        user['last_2fa_attempt'] = datetime.now()
        
        # Формируем ответ
        response_data = {
            "status": "success",
            "message": "Двухфакторная аутентификация успешно пройдена",
            "data": {
                "session_token": session_info['session_token'],
                "user": {
                    "id": user['id'],
                    "username": user['username'],
                    "email": user['email'],
                    "two_fa_enabled": user['two_fa_enabled']
                },
                "session_expires_at": session_info['session_data']['expires_at'].isoformat(),
                "is_backup_code_used": is_backup_code,
                "remaining_backup_codes": len(user.get('two_fa_backup_codes', []))
            }
        }
        
        response = JSONResponse(content=response_data)
        
        # Устанавливаем cookie с сессией
        response.set_cookie(
            key="session_token",
            value=session_info['session_token'],
            httponly=True,
            secure=True,  # В production установить True
            samesite="strict",
            max_age=TWO_FACTOR_CONFIG['session_duration_hours'] * 3600
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Ошибка при верификации 2FA: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера при верификации 2FA"
        )

# Вспомогательные эндпоинты для работы с 2FA
@app.post("/2fa/setup", status_code=status.HTTP_200_OK)
async def two_factor_setup(request: Request):
    """Начало настройки 2FA (требуется аутентификация)"""
    # В реальном проекте здесь должна быть проверка аутентификации
    user_id = 1  # Пример: берем первого пользователя
    
    user = fake_users_db.get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    # Генерируем новый секрет
    secret = generate_totp_secret()
    
    # Генерируем резервные коды
    backup_codes = generate_backup_codes()
    hashed_backup_codes = [hash_backup_code(code) for code in backup_codes]
    
    # Генерируем QR-код
    qr_code = generate_qr_code(secret, user['username'])
    
    # Сохраняем временные данные (в реальном проекте в БД)
    two_factor_secrets[user_id] = {
        'secret': secret,
        'backup_codes': hashed_backup_codes,
        'created_at': datetime.now()
    }
    
    return {
        "status": "success",
        "data": {
            "secret": secret,  # В production лучше не возвращать, только в QR-коде
            "qr_code": qr_code,
            "backup_codes": backup_codes,  # Важно показать пользователю один раз
            "message": "Сохраните резервные коды в безопасном месте"
        }
    }

@app.post("/2fa/enable", status_code=status.HTTP_200_OK)
async def two_factor_enable(request_data: TwoFactorVerifyRequest, request: Request):
    """Активация 2FA после настройки"""
    user_id = 1  # Пример: берем первого пользователя
    
    user = fake_users_db.get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    # Получаем временные данные настройки
    temp_data = two_factor_secrets.get(user_id)
    if not temp_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала выполните настройку 2FA"
        )
    
    # Проверяем код
    if not verify_totp_code(temp_data['secret'], request_data.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный код подтверждения"
        )
    
    # Активируем 2FA
    user['two_fa_enabled'] = True
    user['two_fa_secret'] = temp_data['secret']
    user['two_fa_backup_codes'] = temp_data['backup_codes']
    user['two_fa_setup_date'] = datetime.now()
    
    # Удаляем временные данные
    del two_factor_secrets[user_id]
    
    return {
        "status": "success",
        "message": "Двухфакторная аутентификация успешно активирована",
        "data": {
            "enabled": True,
            "setup_date": user['two_fa_setup_date'].isoformat(),
            "remaining_backup_codes": len(user['two_fa_backup_codes'])
        }
    }

@app.post("/2fa/disable", status_code=status.HTTP_200_OK)
async def two_factor_disable(request_data: TwoFactorVerifyRequest, request: Request):
    """Отключение 2FA"""
    user_id = 1  # Пример: берем первого пользователя
    
    user = fake_users_db.get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    if not user.get('two_fa_enabled', False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA не включена для этого аккаунта"
        )
    
    # Проверяем код для подтверждения
    secret = user.get('two_fa_secret')
    if secret and not verify_totp_code(secret, request_data.code):
        # Проверяем резервный код
        if not verify_backup_code(request_data.code, user.get('two_fa_backup_codes', [])):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный код подтверждения"
            )
    
    # Отключаем 2FA
    user['two_fa_enabled'] = False
    user['two_fa_secret'] = None
    user['two_fa_backup_codes'] = []
    
    return {
        "status": "success",
        "message": "Двухфакторная аутентификация отключена"
    }

@app.get("/2fa/status", status_code=status.HTTP_200_OK)
async def two_factor_status(request: Request):
    """Получение статуса 2FA"""
    user_id = 1  # Пример: берем первого пользователя
    
    user = fake_users_db.get(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    return TwoFactorStatus(
        is_enabled=user.get('two_fa_enabled', False),
        setup_date=user.get('two_fa_setup_date'),
        last_used=user.get('last_2fa_attempt')
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)