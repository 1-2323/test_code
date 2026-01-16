import secrets
import time
import jwt
import pyotp
import qrcode
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import redis
import io
import base64


@dataclass
class MFAConfig:
    """Конфигурация двухфакторной аутентификации"""
    otp_timeout: int = 300  # 5 минут в секундах
    jwt_secret: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration: int = 3600  # 1 час в секундах
    otp_digits: int = 6
    otp_interval: int = 30


class MFAService:
    """Сервис двухфакторной аутентификации"""
    
    def __init__(self, redis_client: redis.Redis, config: Optional[MFAConfig] = None):
        """
        Инициализация сервиса MFA.
        
        Args:
            redis_client: Клиент Redis для хранения OTP
            config: Конфигурация MFA (опционально)
        """
        self.redis = redis_client
        self.config = config or MFAConfig()
    
    def _generate_otp_key(self, user_id: str) -> str:
        """Генерация ключа для хранения OTP в Redis"""
        return f"mfa:otp:{user_id}"
    
    def _generate_jwt_token(self, user_id: str, mfa_verified: bool = False) -> str:
        """
        Генерация JWT токена.
        
        Args:
            user_id: Идентификатор пользователя
            mfa_verified: Флаг верификации MFA
            
        Returns:
            JWT токен
        """
        payload = {
            'user_id': user_id,
            'mfa_verified': mfa_verified,
            'exp': datetime.utcnow() + timedelta(seconds=self.config.jwt_expiration),
            'iat': datetime.utcnow(),
        }
        
        return jwt.encode(
            payload, 
            self.config.jwt_secret, 
            algorithm=self.config.jwt_algorithm
        )
    
    def setup_mfa(self, user_id: str, user_email: str) -> Dict[str, Any]:
        """
        Настройка MFA для пользователя.
        
        Args:
            user_id: Идентификатор пользователя
            user_email: Email пользователя
            
        Returns:
            Данные для настройки MFA (секрет, QR код)
        """
        # Генерация секрета для TOTP
        secret = pyotp.random_base32()
        
        # Создание TOTP объекта
        totp = pyotp.TOTP(
            secret, 
            digits=self.config.otp_digits, 
            interval=self.config.otp_interval
        )
        
        # Генерация URI для QR кода
        provisioning_uri = totp.provisioning_uri(
            name=user_email,
            issuer_name="YourApp"
        )
        
        # Генерация QR кода в base64
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Конвертация изображения в base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        # Сохраняем секрет в Redis (в реальном приложении - в защищенное хранилище)
        secret_key = f"mfa:secret:{user_id}"
        self.redis.setex(secret_key, 86400, secret)  # 24 часа на настройку
        
        return {
            'secret': secret,
            'qr_code': f"data:image/png;base64,{qr_base64}",
            'provisioning_uri': provisioning_uri,
        }
    
    def verify_otp(self, user_id: str, otp_code: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Верификация OTP кода.
        
        Args:
            user_id: Идентификатор пользователя
            otp_code: OTP код от пользователя
            
        Returns:
            Кортеж (успешность, JWT токен, сообщение об ошибке)
        """
        # Проверяем, есть ли активный OTP запрос
        otp_key = self._generate_otp_key(user_id)
        
        if not self.redis.exists(otp_key):
            return False, None, "No active OTP request found"
        
        # Получаем секрет пользователя (в реальном приложении - из защищенного хранилища)
        secret_key = f"mfa:secret:{user_id}"
        secret = self.redis.get(secret_key)
        
        if not secret:
            return False, None, "MFA not configured for this user"
        
        # Проверяем OTP
        totp = pyotp.TOTP(
            secret.decode(),
            digits=self.config.otp_digits,
            interval=self.config.otp_interval
        )
        
        if not totp.verify(otp_code):
            # Увеличиваем счетчик неудачных попыток
            attempts_key = f"mfa:attempts:{user_id}"
            current_attempts = self.redis.incr(attempts_key)
            self.redis.expire(attempts_key, 300)  # Сбрасываем через 5 минут
            
            if current_attempts >= 5:
                self.redis.delete(otp_key)  # Удаляем OTP запрос
                return False, None, "Too many failed attempts. Please request new OTP"
            
            return False, None, "Invalid OTP code"
        
        # OTP успешно верифицирован
        # Удаляем использованный OTP запрос и сбрасываем счетчик попыток
        self.redis.delete(otp_key)
        self.redis.delete(f"mfa:attempts:{user_id}")
        
        # Генерируем финальный JWT токен
        jwt_token = self._generate_jwt_token(user_id, mfa_verified=True)
        
        return True, jwt_token, None
    
    def initiate_otp_verification(self, user_id: str) -> bool:
        """
        Инициация процесса верификации OTP.
        
        Args:
            user_id: Идентификатор пользователя
            
        Returns:
            True если процесс инициирован успешно
        """
        otp_key = self._generate_otp_key(user_id)
        
        # Сохраняем флаг того, что пользователь ожидает OTP
        self.redis.setex(otp_key, self.config.otp_timeout, "pending")
        
        return True
    
    def get_user_mfa_status(self, user_id: str) -> Dict[str, bool]:
        """
        Получение статуса MFA для пользователя.
        
        Args:
            user_id: Идентификатор пользователя
            
        Returns:
            Словарь с информацией о статусе MFA
        """
        secret_key = f"mfa:secret:{user_id}"
        has_secret = bool(self.redis.exists(secret_key))
        
        return {
            'mfa_enabled': has_secret,
            'mfa_setup_complete': has_secret,
        }


# Пример эндпоинта FastAPI для /verify-otp
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

router = APIRouter()

class VerifyOTPRequest(BaseModel):
    user_id: str
    otp_code: str

@router.post("/verify-otp")
async def verify_otp_endpoint(request: VerifyOTPRequest, mfa_service: MFAService = Depends()):
    '''
    Эндпоинт для верификации OTP кода.
    
    Args:
        request: Запрос с user_id и otp_code
        
    Returns:
        JWT токен при успешной верификации
    '''
    success, jwt_token, error_message = mfa_service.verify_otp(
        request.user_id, 
        request.otp_code
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=error_message)
    
    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "expires_in": mfa_service.config.jwt_expiration
    }
"""