from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session
from redis import Redis
import pyotp
import uuid

# Модели запроса/ответа
class Verify2FARequest(BaseModel):
    verification_code: constr(min_length=6, max_length=6, pattern=r'^\d{6}$')
    temp_session_id: uuid.UUID

class Verify2FAResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

# Зависимости и конфигурация
router = APIRouter(prefix="/2fa", tags=["2fa"])

# Конфигурация
VERIFICATION_MAX_ATTEMPTS = 3
VERIFICATION_CODE_TTL = 300  # 5 минут
ATTEMPT_WINDOW_TTL = 900     # 15 минут
LOCKOUT_DURATION = 1800      # 30 минут при блокировке

class TwoFactorAuthService:
    def __init__(self, redis_client: Redis, db_session: Session):
        self.redis = redis_client
        self.db = db_session
    
    def _get_attempts_key(self, temp_session_id: str) -> str:
        return f"2fa:attempts:{temp_session_id}"
    
    def _get_lockout_key(self, temp_session_id: str) -> str:
        return f"2fa:lockout:{temp_session_id}"
    
    def _get_temp_session_key(self, temp_session_id: str) -> str:
        return f"2fa:temp_session:{temp_session_id}"
    
    def check_lockout(self, temp_session_id: str) -> None:
        """Проверяет, заблокирован ли пользователь"""
        lockout_key = self._get_lockout_key(temp_session_id)
        if self.redis.exists(lockout_key):
            ttl = self.redis.ttl(lockout_key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Слишком много попыток. Попробуйте снова через {ttl} секунд"
            )
    
    def increment_attempts(self, temp_session_id: str) -> int:
        """Увеличивает счетчик попыток и возвращает текущее количество"""
        attempts_key = self._get_attempts_key(temp_session_id)
        
        # Создаем или увеличиваем счетчик
        current_attempts = self.redis.incr(attempts_key)
        
        # Если это первая попытка, устанавливаем TTL
        if current_attempts == 1:
            self.redis.expire(attempts_key, ATTEMPT_WINDOW_TTL)
        
        # Если превышено максимальное количество попыток - блокируем
        if current_attempts >= VERIFICATION_MAX_ATTEMPTS:
            lockout_key = self._get_lockout_key(temp_session_id)
            self.redis.setex(lockout_key, LOCKOUT_DURATION, "locked")
            self.redis.delete(attempts_key)  # Очищаем счетчик попыток
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Превышено максимальное количество попыток. Аккаунт заблокирован на {LOCKOUT_DURATION // 60} минут"
            )
        
        return current_attempts
    
    def get_temp_session_data(self, temp_session_id: str) -> Optional[Dict[str, Any]]:
        """Получает временные данные сессии"""
        session_key = self._get_temp_session_key(temp_session_id)
        data = self.redis.get(session_key)
        if data:
            return eval(data)  # В production используйте безопасную десериализацию
        return None
    
    def verify_totp_code(self, secret: str, code: str) -> bool:
        """Верифицирует TOTP код"""
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)  # Разрешаем небольшое отклонение
    
    def clear_verification_data(self, temp_session_id: str) -> None:
        """Очищает временные данные верификации"""
        keys_to_delete = [
            self._get_temp_session_key(temp_session_id),
            self._get_attempts_key(temp_session_id),
            self._get_lockout_key(temp_session_id)
        ]
        self.redis.delete(*keys_to_delete)
    
    def generate_tokens(self, user_id: int) -> Dict[str, Any]:
        """Генерирует JWT токены для пользователя"""
        # Здесь реализуйте генерацию токенов
        # Например, используя python-jose или PyJWT
        access_token = f"access_token_{user_id}_{uuid.uuid4()}"
        refresh_token = f"refresh_token_{user_id}_{uuid.uuid4()}"
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": 3600
        }

# Зависимости (должны быть реализованы в основном приложении)
def get_redis_client() -> Redis:
    # Возвращает экземпляр Redis клиента
    return Redis(host='localhost', port=6379, db=0)

def get_db_session() -> Session:
    # Возвращает сессию базы данных
    pass

def get_2fa_service(
    redis: Redis = Depends(get_redis_client),
    db: Session = Depends(get_db_session)
) -> TwoFactorAuthService:
    return TwoFactorAuthService(redis, db)

@router.post("/verify", response_model=Verify2FAResponse)
async def verify_2fa_code(
    request: Verify2FARequest,
    service: TwoFactorAuthService = Depends(get_2fa_service)
):
    """
    Верифицирует одноразовый код двухфакторной аутентификации
    """
    temp_session_id = str(request.temp_session_id)
    
    # 1. Проверяем блокировку
    try:
        service.check_lockout(temp_session_id)
    except HTTPException:
        raise
    
    # 2. Получаем данные временной сессии
    session_data = service.get_temp_session_data(temp_session_id)
    
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сессия истекла или не найдена"
        )
    
    # 3. Проверяем код
    user_id = session_data.get("user_id")
    secret_key = session_data.get("secret_key")
    
    if not all([user_id, secret_key]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверные данные сессии"
        )
    
    # 4. Верифицируем код
    is_valid = service.verify_totp_code(secret_key, request.verification_code)
    
    if not is_valid:
        # Увеличиваем счетчик попыток
        current_attempts = service.increment_attempts(temp_session_id)
        remaining_attempts = VERIFICATION_MAX_ATTEMPTS - current_attempts
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неверный код. Осталось попыток: {remaining_attempts}"
        )
    
    # 5. Код верный - генерируем токены
    tokens = service.generate_tokens(user_id)
    
    # 6. Очищаем временные данные
    service.clear_verification_data(temp_session_id)
    
    # 7. Обновляем время последнего входа (пример)
    # user = db.query(User).filter(User.id == user_id).first()
    # user.last_login_at = datetime.utcnow()
    # db.commit()
    
    return Verify2FAResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens["expires_in"]
    )

# Дополнительные утилиты
def create_temp_session(
    redis: Redis,
    user_id: int,
    secret_key: str,
    additional_data: Optional[Dict] = None
) -> str:
    """Создает временную сессию для 2FA"""
    temp_session_id = str(uuid.uuid4())
    session_data = {
        "user_id": user_id,
        "secret_key": secret_key,
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(seconds=VERIFICATION_CODE_TTL)).isoformat()
    }
    
    if additional_data:
        session_data.update(additional_data)
    
    session_key = f"2fa:temp_session:{temp_session_id}"
    redis.setex(session_key, VERIFICATION_CODE_TTL, str(session_data))
    
    return temp_session_id