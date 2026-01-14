import os
import base64
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.exceptions import InvalidTag

from fastapi import FastAPI, HTTPException, Depends, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Конфигурация
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-change-in-production")
    DB_URL = os.environ.get("DATABASE_URL", "sqlite:///./sensitive_data.db")
    ENCRYPTION_KEY_SALT = os.environ.get("ENCRYPTION_KEY_SALT", "fixed-salt-change-in-production").encode()
    ENCRYPTION_ITERATIONS = 100000
    ENCRYPTION_KEY_LENGTH = 32
    ENCRYPTION_ALGORITHM = algorithms.AES
    ENCRYPTION_MODE = modes.GCM
    ENCRYPTION_TAG_LENGTH = 16
    MIN_PASSPHRASE_LENGTH = 12

config = Config()

# Модель данных Pydantic
class SensitiveDataRequest(BaseModel):
    card_number: str = Field(..., min_length=12, max_length=19, description="Номер карты")
    card_holder: Optional[str] = Field(None, max_length=100, description="Держатель карты")
    expiry_date: Optional[str] = Field(None, regex=r'^(0[1-9]|1[0-2])\/([0-9]{2})$', description="ММ/ГГ")
    cvv: Optional[str] = Field(None, min_length=3, max_length=4, description="CVV код")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Дополнительные метаданные")
    
    @validator('card_number')
    def validate_card_number(cls, v):
        # Удаляем пробелы и дефисы для валидации
        clean_number = v.replace(' ', '').replace('-', '')
        if not clean_number.isdigit():
            raise ValueError('Номер карты должен содержать только цифры')
        # Простая проверка алгоритмом Луна
        if not cls._luhn_check(clean_number):
            raise ValueError('Неверный номер карты (проверка алгоритмом Луна)')
        return v
    
    @staticmethod
    def _luhn_check(card_number: str) -> bool:
        def digits_of(n):
            return [int(d) for d in str(n)]
        digits = digits_of(card_number)
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        checksum = sum(odd_digits)
        for d in even_digits:
            checksum += sum(digits_of(d*2))
        return checksum % 10 == 0

class SensitiveDataResponse(BaseModel):
    id: int
    encrypted_data: str
    encryption_version: str
    created_at: datetime
    updated_at: datetime

# Инициализация базы данных
Base = declarative_base()

class SensitiveDataRecord(Base):
    __tablename__ = 'sensitive_data_records'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    encrypted_data = Column(Text, nullable=False)
    encryption_version = Column(String(50), nullable=False)
    nonce = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

# Создаем движок и таблицы
engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False} if "sqlite" in config.DB_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

# Зависимости
security = HTTPBearer()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    # Здесь должна быть реальная аутентификация пользователя
    # Для примера используем токен как user_id
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не авторизован"
        )
    return credentials.credentials

# Сервис шифрования
class EncryptionService:
    VERSION = "AES-GCM-v1"
    
    def __init__(self, secret_key: str, salt: bytes, iterations: int = config.ENCRYPTION_ITERATIONS):
        self.secret_key = secret_key
        self.salt = salt
        self.iterations = iterations
        
    def _derive_key(self) -> bytes:
        """Генерация ключа шифрования из секрета"""
        kdf = PBKDF2(
            algorithm=hashlib.SHA256(),
            length=config.ENCRYPTION_KEY_LENGTH,
            salt=self.salt,
            iterations=self.iterations,
            backend=default_backend()
        )
        return kdf.derive(self.secret_key.encode())
    
    def encrypt(self, plaintext: str) -> Dict[str, str]:
        """Шифрование данных с использованием AES-GCM"""
        key = self._derive_key()
        
        # Генерация случайного nonce для GCM
        nonce = os.urandom(12)
        
        # Создание шифра
        cipher = Cipher(
            config.ENCRYPTION_ALGORITHM(key),
            config.ENCRYPTION_MODE(nonce),
            backend=default_backend()
        )
        
        encryptor = cipher.encryptor()
        
        # Добавление padding для данных
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext.encode()) + padder.finalize()
        
        # Шифрование
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        
        # Получение тега аутентификации
        tag = encryptor.tag
        
        # Объединяем ciphertext и tag
        encrypted_data = ciphertext + tag
        
        return {
            "encrypted": base64.b64encode(encrypted_data).decode('utf-8'),
            "nonce": base64.b64encode(nonce).decode('utf-8')
        }
    
    def decrypt(self, encrypted_data: str, nonce: str) -> str:
        """Расшифровка данных"""
        key = self._derive_key()
        
        # Декодирование из base64
        encrypted_bytes = base64.b64decode(encrypted_data)
        nonce_bytes = base64.b64decode(nonce)
        
        # Разделение ciphertext и tag
        ciphertext = encrypted_bytes[:-config.ENCRYPTION_TAG_LENGTH]
        tag = encrypted_bytes[-config.ENCRYPTION_TAG_LENGTH:]
        
        # Создание шифра для расшифровки
        cipher = Cipher(
            config.ENCRYPTION_ALGORITHM(key),
            config.ENCRYPTION_MODE(nonce_bytes, tag),
            backend=default_backend()
        )
        
        decryptor = cipher.decryptor()
        
        try:
            # Расшифровка
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            
            # Удаление padding
            unpadder = padding.PKCS7(128).unpadder()
            plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
            
            return plaintext.decode('utf-8')
        except (InvalidTag, ValueError) as e:
            raise ValueError("Не удалось расшифровать данные") from e

# Инициализация FastAPI
app = FastAPI(
    title="API для защиты конфиденциальных данных",
    description="Эндпоинты для безопасного хранения чувствительной информации",
    version="1.0.0"
)

# Инициализация сервиса шифрования
encryption_service = EncryptionService(
    secret_key=config.SECRET_KEY,
    salt=config.ENCRYPTION_KEY_SALT,
    iterations=config.ENCRYPTION_ITERATIONS
)

@app.post(
    "/profile/save-sensitive",
    response_model=SensitiveDataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Сохранение конфиденциальных данных",
    description="""Принимает чувствительные данные (номер карты и т.д.), 
    шифрует их на уровне приложения и сохраняет в базе данных."""
)
async def save_sensitive_data(
    data: SensitiveDataRequest,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # Преобразуем данные в JSON для шифрования
        import json
        plaintext_data = data.json()
        
        # Шифруем данные
        encrypted_result = encryption_service.encrypt(plaintext_data)
        
        # Создаем запись в базе данных
        db_record = SensitiveDataRecord(
            user_id=user_id,
            encrypted_data=encrypted_result["encrypted"],
            encryption_version=EncryptionService.VERSION,
            nonce=encrypted_result["nonce"]
        )
        
        db.add(db_record)
        db.commit()
        db.refresh(db_record)
        
        return SensitiveDataResponse(
            id=db_record.id,
            encrypted_data=db_record.encrypted_data,
            encryption_version=db_record.encryption_version,
            created_at=db_record.created_at,
            updated_at=db_record.updated_at
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка при обработке данных: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

# Эндпоинт для получения зашифрованных данных (для демонстрации)
@app.get(
    "/profile/sensitive/{record_id}",
    summary="Получение зашифрованных данных",
    description="""Возвращает расшифрованные данные по ID записи. 
    Требуется аутентификация и проверка прав доступа."""
)
async def get_sensitive_data(
    record_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Получаем запись из базы данных
    record = db.query(SensitiveDataRecord).filter(
        SensitiveDataRecord.id == record_id,
        SensitiveDataRecord.user_id == user_id
    ).first()
    
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запись не найдена или у вас нет к ней доступа"
        )
    
    try:
        # Расшифровываем данные
        decrypted_data = encryption_service.decrypt(
            record.encrypted_data,
            record.nonce
        )
        
        # Преобразуем JSON обратно в словарь
        import json
        data_dict = json.loads(decrypted_data)
        
        # Маскируем номер карты перед возвратом
        if 'card_number' in data_dict:
            card_num = data_dict['card_number']
            if len(card_num) > 4:
                data_dict['card_number'] = '****' + card_num[-4:]
        
        return {
            "id": record.id,
            "data": data_dict,
            "created_at": record.created_at,
            "updated_at": record.updated_at
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при расшифровке данных"
        )

# Middleware для логирования запросов к чувствительным эндпоинтам
@app.middleware("http")
async def log_sensitive_requests(request, call_next):
    if "/profile/sensitive" in request.url.path:
        # Здесь должна быть логика логирования с маскировкой данных
        pass
    
    response = await call_next(request)
    return response