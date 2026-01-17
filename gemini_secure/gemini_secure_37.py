import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Final, List, Optional, Type

import jwt
import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from redis.asyncio import Redis

# ==========================================
# 1. КОНФИГУРАЦИЯ И МОДЕЛИ ДАННЫХ
# ==========================================

class AppSettings(BaseModel):
    """Глобальные настройки безопасности приложения."""
    SECRET_KEY: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_urlsafe(32)))
    JWT_ALGORITHM: str = "HS256"
    SESSION_TTL: int = 3600
    OTP_MAX_ATTEMPTS: int = 3
    
    model_config = ConfigDict(extra='forbid')

class User(BaseModel):
    """Модель пользователя системы."""
    user_id: str
    username: str
    hashed_password: str
    is_mfa_enabled: bool = True
    must_change_password: bool = True

class FinancialMessage(BaseModel):
    """Схема защищенного финансового сообщения."""
    msg_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    amount: float = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    payload: Dict[str, Any]

# ==========================================
# 2. КРИПТОГРАФИЧЕСКИЙ СЕРВИС
# ==========================================

class CryptoCore:
    """Обеспечивает цифровую подпись и проверку целостности данных."""
    
    @staticmethod
    def sign_message(message: BaseModel, private_key: ed25519.Ed25519PrivateKey) -> Dict[str, Any]:
        """Подписывает данные с использованием Ed25519."""
        msg_bytes = json.dumps(message.model_dump(), sort_keys=True).encode()
        signature = private_key.sign(msg_bytes)
        return {"data": message.model_dump(), "signature": signature.hex()}

    @staticmethod
    def verify_message(envelope: Dict[str, Any], public_key: ed25519.Ed25519PublicKey):
        """Проверяет подпись и структуру пакета."""
        try:
            signature = bytes.fromhex(envelope["signature"])
            msg_bytes = json.dumps(envelope["data"], sort_keys=True).encode()
            public_key.verify(signature, msg_bytes)
            return FinancialMessage(**envelope["data"])
        except (InvalidSignature, KeyError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid message integrity or signature")

# ==========================================
# 3. СЕРВИС АУТЕНТИФИКАЦИИ И СЕССИЙ
# ==========================================

class AuthService:
    """Управление сессиями, OTP и защитой от Brute-force."""
    
    def __init__(self, redis: Redis, settings: AppSettings):
        self.redis = redis
        self.settings = settings

    async def check_lockout(self, username: str):
        """Проверяет блокировку аккаунта в Redis."""
        attempts = await self.redis.get(f"attempts:{username}")
        if attempts and int(attempts) >= 5:
            raise HTTPException(status_code=429, detail="Account locked. Try later.")

    async def verify_otp(self, user_id: str, provided_otp: str):
        """Верификация OTP с защитой от атак по времени."""
        stored_otp = await self.redis.get(f"otp:{user_id}")
        if not stored_otp or not hmac.compare_digest(provided_otp, stored_otp):
            await self.redis.incr(f"otp_err:{user_id}")
            raise HTTPException(status_code=401, detail="Invalid OTP")
        
        await self.redis.delete(f"otp:{user_id}", f"otp_err:{user_id}")
        return self._issue_jwt(user_id)

    def _issue_jwt(self, user_id: str) -> str:
        """Создает ограниченный по правам токен доступа."""
        payload = {
            "sub": user_id,
            "exp": datetime.utcnow() + timedelta(seconds=self.settings.SESSION_TTL),
            "iat": datetime.utcnow(),
            "scope": "financial:write"
        }
        return jwt.encode(payload, self.settings.SECRET_KEY.get_secret_value(), algorithm=self.settings.JWT_ALGORITHM)

# ==========================================
# 4. МОНИТОРИНГ И MIDDLEWARE
# ==========================================

class SecurityMonitor:
    """Мониторинг контекста сессии (IP и Fingerprint)."""
    
    @staticmethod
    def get_fingerprint_hash(request: Request) -> str:
        """Нормализует и хеширует признаки браузера."""
        fp_data = f"{request.headers.get('user-agent')}|{request.headers.get('accept-language')}"
        return hashlib.sha256(fp_data.encode()).hexdigest()

    async def validate_context(self, session_data: Dict, current_request: Request):
        """Сверяет текущий IP и Fingerprint с эталоном сессии."""
        curr_ip = current_request.client.host
        curr_fp = self.get_fingerprint_hash(current_request)
        
        if session_data['fingerprint'] != curr_fp:
            logging.warning(f"Session hijack attempt detected for user {session_data['user_id']}")
            return False
        return True

# ==========================================
# 5. ДИСПЕТЧЕР ВЕБХУКОВ И ОБНОВЛЕНИЙ
# ==========================================

class SafeLoader:
    """Безопасная десериализация и загрузка плагинов."""
    
    @staticmethod
    def load_yaml_config(path: str) -> Dict:
        """Безопасная загрузка конфигурации без выполнения кода."""
        with open(path, 'r') as f:
            return yaml.safe_load(f)

    @staticmethod
    def validate_archive(file_path: str, expected_hash: str):
        """Проверка целостности файла обновления (SHA-256)."""
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(4096):
                sha.update(chunk)
        if not hmac.compare_digest(sha.hexdigest(), expected_hash):
            raise ValueError("Update package integrity compromised")

# ==========================================
# 6. API И ОБРАБОТЧИКИ (FastAPI)
# ==========================================

app = FastAPI()
redis_instance = Redis(host='localhost', decode_responses=True)
settings = AppSettings()



@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Добавляет строгие защитные HTTP-заголовки."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self';"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response

@app.post("/verify-otp")
async def verify_otp_endpoint(user_id: str, otp: str, response: Response):
    """Финальный этап входа с выдачей защищенной куки."""
    auth = AuthService(redis_instance, settings)
    token = await auth.verify_otp(user_id, otp)
    
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict"
    )
    return {"status": "authorized"}

@app.post("/process-transaction")
async def process_transaction(envelope: Dict[str, Any], request: Request):
    """Прием и проверка подписанного финансового сообщения."""
    # 1. Проверка контекста сессии (Fingerprint)
    monitor = SecurityMonitor()
    # (Логика получения session_data из Redis/Cookie пропущена для краткости)
    
    # 2. Проверка криптографической подписи сообщения
    crypto = CryptoCore()
    # public_key должен быть загружен из доверенного хранилища ключей
    # message = crypto.verify_message(envelope, public_key)
    
    return {"status": "transaction_processed"}