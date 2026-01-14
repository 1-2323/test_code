import base64
import hashlib
import os
from datetime import datetime
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, validator
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Конфигурация
DATABASE_URL = "postgresql://user:password@localhost/dbname"
SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here-change-in-production")
SALT = os.environ.get("ENCRYPTION_SALT", "your-unique-salt-here").encode()
ITERATIONS = 100000

# Инициализация FastAPI
app = FastAPI(title="Data Protection API")

# Безопасность
security = HTTPBearer()

# SQLAlchemy
Base = declarative_base()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Модели данных
class SensitiveData(Base):
    __tablename__ = "sensitive_data"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    encrypted_data = Column(Text, nullable=False)
    data_type = Column(String(50), nullable=False)
    iv = Column(String(255), nullable=False)  # Вектор инициализации
    salt = Column(String(255), nullable=False)  # Уникальная соль для каждой записи
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Pydantic схемы
class SensitiveDataRequest(BaseModel):
    card_number: Optional[str] = Field(None, min_length=12, max_length=19)
    passport_number: Optional[str] = Field(None, min_length=5, max_length=20)
    phone_number: Optional[str] = Field(None, min_length=10, max_length=15)
    custom_data: Optional[str] = Field(None, min_length=1, max_length=500)
    data_type: str = Field(..., description="Тип сохраняемых данных")

    @validator('card_number')
    def validate_card_number(cls, v):
        if v is not None:
            # Удаляем пробелы и дефисы
            clean_v = v.replace(" ", "").replace("-", "")
            if not clean_v.isdigit():
                raise ValueError("Номер карты должен содержать только цифры")
            # Простая проверка длины
            if len(clean_v) not in [15, 16, 19]:
                raise ValueError("Неверная длина номера карты")
        return v

    class Config:
        min_anystr_length = 1
        max_anystr_length = 500

class SensitiveDataResponse(BaseModel):
    id: int
    user_id: str
    data_type: str
    created_at: datetime
    updated_at: datetime
    status: str = "success"

# Криптографические утилиты
class CryptoService:
    @staticmethod
    def generate_key_from_secret(secret: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
        """Генерация ключа из секрета с использованием PBKDF2"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        return key

    @staticmethod
    def encrypt_data(data: str, user_id: str) -> tuple[str, str, str]:
        """Шифрование данных с уникальной солью для каждой записи"""
        # Генерация уникальной соли для этой записи
        record_salt = os.urandom(16)
        record_salt_b64 = base64.urlsafe_b64encode(record_salt).decode()
        
        # Создание ключа на основе SECRET_KEY и user_id
        secret_input = f"{SECRET_KEY}:{user_id}"
        key = CryptoService.generate_key_from_secret(secret_input, record_salt)
        
        # Шифрование
        fernet = Fernet(key)
        encrypted_data = fernet.encrypt(data.encode())
        
        # Генерация IV (у Fernet он включен в токен, но мы храним отдельно для совместимости)
        iv = hashlib.sha256(os.urandom(16)).hexdigest()
        
        return base64.urlsafe_b64encode(encrypted_data).decode(), iv, record_salt_b64

    @staticmethod
    def verify_token(token: HTTPAuthorizationCredentials) -> str:
        """Верификация токена и извлечение user_id"""
        # В реальном приложении здесь должна быть проверка JWT или другого токена
        try:
            # Пример: токен в формате "user_id:signature"
            # В продакшене используйте библиотеку для JWT
            import jwt  # был бы импортирован в реальном приложении
            # Для примера просто возвращаем user_id из заголовка
            # В реальности: decoded = jwt.decode(token.credentials, SECRET_KEY, algorithms=["HS256"])
            # return decoded["sub"]
            
            # Заглушка: ожидаем токен в формате "Bearer user123"
            if token.credentials.startswith("user"):
                return token.credentials
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication token"
                )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token"
            )

# Зависимости
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """Получение текущего пользователя из токена"""
    return CryptoService.verify_token(credentials)

# Эндпоинт
@app.post("/profile/save-sensitive", 
          response_model=SensitiveDataResponse,
          status_code=status.HTTP_201_CREATED,
          summary="Сохранение конфиденциальных данных",
          description="Шифрует и сохраняет конфиденциальные данные пользователя в базе данных",
          tags=["Sensitive Data"])
async def save_sensitive_data(
    request: SensitiveDataRequest,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Сохраняет конфиденциальные данные пользователя в зашифрованном виде.
    
    - **card_number**: Номер банковской карты (12-19 цифр)
    - **passport_number**: Номер паспорта
    - **phone_number**: Номер телефона
    - **custom_data**: Произвольные конфиденциальные данные
    - **data_type**: Тип сохраняемых данных (card/passport/phone/custom)
    """
    try:
        # Выбор данных для шифрования
        data_to_encrypt = None
        if request.card_number:
            data_to_encrypt = request.card_number
        elif request.passport_number:
            data_to_encrypt = request.passport_number
        elif request.phone_number:
            data_to_encrypt = request.phone_number
        elif request.custom_data:
            data_to_encrypt = request.custom_data
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No data provided for encryption"
            )

        # Шифрование данных
        encrypted_data, iv, record_salt = CryptoService.encrypt_data(
            data_to_encrypt, 
            current_user
        )

        # Сохранение в базу данных
        db_record = SensitiveData(
            user_id=current_user,
            encrypted_data=encrypted_data,
            data_type=request.data_type,
            iv=iv,
            salt=record_salt
        )

        db.add(db_record)
        db.commit()
        db.refresh(db_record)

        # Логирование (в реальном приложении используйте структурированное логирование)
        app.logger.info(f"Sensitive data saved for user {current_user}, type: {request.data_type}")

        return SensitiveDataResponse(
            id=db_record.id,
            user_id=db_record.user_id,
            data_type=db_record.data_type,
            created_at=db_record.created_at,
            updated_at=db_record.updated_at
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Общий обработчик ошибок
        db.rollback()
        # В продакшене не показывайте детали ошибки клиенту
        app.logger.error(f"Error saving sensitive data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

# Дополнительные эндпоинты для демонстрации
@app.get("/health")
async def health_check():
    """Проверка работоспособности сервиса"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        ssl_keyfile="key.pem",  # Для HTTPS в продакшене
        ssl_certfile="cert.pem"
    )