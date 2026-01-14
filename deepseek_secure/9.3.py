import logging
import json
import re
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum
import uuid

from fastapi import FastAPI, Request, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, String, DateTime, Enum as SQLEnum, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('payment_transactions.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
DATABASE_URL = "sqlite:///./payments.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Enum для статусов транзакции
class TransactionStatus(str, Enum):
    INITIATED = "initiated"
    CARD_VALIDATED = "card_validated"
    PAYMENT_PROCESSING = "payment_processing"
    BANK_REQUEST_SENT = "bank_request_sent"
    BANK_RESPONSE_RECEIVED = "bank_response_received"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"

# Pydantic модели
class PaymentCard(BaseModel):
    card_number: str = Field(..., description="Номер карты (PAN)")
    expiry_date: str = Field(..., description="Срок действия (MM/YY)")
    cvv: str = Field(..., description="CVV код")
    cardholder_name: str = Field(..., description="Имя держателя карты")

    @validator('card_number')
    def mask_card_number(cls, v):
        """Маскирует номер карты для логов"""
        if len(v) < 4:
            return v
        return f"{'*' * (len(v) - 4)}{v[-4:]}"

class PaymentRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field("RUB", description="Валюта")
    order_id: str = Field(..., description="ID заказа")
    customer_id: str = Field(..., description="ID клиента")
    card: PaymentCard
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class TransactionLog(BaseModel):
    transaction_id: str
    status: TransactionStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime

# Модель БД
class TransactionLogDB(Base):
    __tablename__ = "transaction_logs"
    
    id = Column(String, primary_key=True, index=True)
    transaction_id = Column(String, index=True)
    status = Column(SQLEnum(TransactionStatus))
    message = Column(Text)
    details = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow)
    order_id = Column(String, index=True)
    customer_id = Column(String, index=True)
    masked_card_number = Column(String)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Зависимости
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Утилиты для маскировки данных
class DataMasker:
    @staticmethod
    def mask_pan(pan: str) -> str:
        """Маскирует номер карты согласно PCI DSS"""
        if len(pan) < 8:
            return pan
        return f"{pan[:6]}{'*' * (len(pan) - 10)}{pan[-4:]}"
    
    @staticmethod
    def mask_cvv(cvv: str) -> str:
        """Маскирует CVV"""
        return "***"
    
    @staticmethod
    def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """Маскирует все чувствительные данные в словаре"""
        masked = data.copy()
        
        # Паттерны для поиска чувствительных данных
        pan_patterns = [r'pan', r'card_number', r'cardNumber', r'account_number']
        cvv_patterns = [r'cvv', r'cvc', r'cid']
        
        for key, value in data.items():
            if isinstance(value, str):
                key_lower = key.lower()
                # Проверка на номер карты
                if any(pattern in key_lower for pattern in pan_patterns):
                    masked[key] = DataMasker.mask_pan(value)
                # Проверка на CVV
                elif any(pattern in key_lower for pattern in cvv_patterns):
                    masked[key] = DataMasker.mask_cvv(value)
        
        return masked

# Сервис логирования транзакций
class TransactionLogger:
    def __init__(self, db: Session):
        self.db = db
        self.masker = DataMasker()
    
    def log_transaction(
        self,
        transaction_id: str,
        status: TransactionStatus,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        order_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        masked_card_number: Optional[str] = None
    ):
        """Логирует этап транзакции в БД и файл"""
        
        # Маскируем чувствительные данные
        safe_details = self.masker.mask_sensitive_data(details) if details else None
        
        # Запись в БД
        db_log = TransactionLogDB(
            id=str(uuid.uuid4()),
            transaction_id=transaction_id,
            status=status,
            message=message,
            details=safe_details,
            order_id=order_id,
            customer_id=customer_id,
            masked_card_number=masked_card_number
        )
        
        self.db.add(db_log)
        self.db.commit()
        
        # Структурированное логирование в файл
        log_entry = {
            "transaction_id": transaction_id,
            "status": status.value,
            "message": message,
            "details": safe_details,
            "timestamp": datetime.utcnow().isoformat(),
            "order_id": order_id,
            "customer_id": customer_id
        }
        
        # Логирование в соответствующий уровень
        if status == TransactionStatus.FAILED:
            logger.error(json.dumps(log_entry, ensure_ascii=False))
        elif status in [TransactionStatus.COMPLETED, TransactionStatus.REFUNDED]:
            logger.info(json.dumps(log_entry, ensure_ascii=False))
        else:
            logger.debug(json.dumps(log_entry, ensure_ascii=False))

# Инициализация FastAPI приложения
app = FastAPI(title="Payment Transaction Logger", version="1.0.0")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware для логирования входящих запросов"""
    request_id = str(uuid.uuid4())
    
    logger.debug(f"Request {request_id}: {request.method} {request.url.path}")
    
    response = await call_next(request)
    
    logger.debug(f"Response {request_id}: Status {response.status_code}")
    
    return response

@app.post("/api/v1/payments/process")
async def process_payment(
    payment_request: PaymentRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Эндпоинт для обработки платежа с полным логированием всех этапов
    """
    transaction_id = str(uuid.uuid4())
    logger_service = TransactionLogger(db)
    
    try:
        # Маскируем номер карты для безопасного хранения
        masked_pan = DataMasker.mask_pan(payment_request.card.card_number)
        
        # 1. Начало транзакции
        logger_service.log_transaction(
            transaction_id=transaction_id,
            status=TransactionStatus.INITIATED,
            message="Транзакция инициирована",
            details={
                "order_id": payment_request.order_id,
                "customer_id": payment_request.customer_id,
                "amount": payment_request.amount,
                "currency": payment_request.currency
            },
            order_id=payment_request.order_id,
            customer_id=payment_request.customer_id,
            masked_card_number=masked_pan
        )
        
        # 2. Валидация карты (без логирования CVV и полного PAN)
        logger_service.log_transaction(
            transaction_id=transaction_id,
            status=TransactionStatus.CARD_VALIDATED,
            message="Данные карты валидированы",
            details={
                "card_last_4": payment_request.card.card_number[-4:],
                "expiry_date": payment_request.card.expiry_date,
                "cardholder_name": payment_request.card.cardholder_name
                # CVV и полный PAN не логируются!
            },
            order_id=payment_request.order_id,
            customer_id=payment_request.customer_id
        )
        
        # 3. Начало обработки платежа
        logger_service.log_transaction(
            transaction_id=transaction_id,
            status=TransactionStatus.PAYMENT_PROCESSING,
            message="Начата обработка платежа",
            details={
                "amount": payment_request.amount,
                "currency": payment_request.currency,
                "metadata": payment_request.metadata
            },
            order_id=payment_request.order_id,
            customer_id=payment_request.customer_id
        )
        
        # 4. Имитация запроса к банку
        logger_service.log_transaction(
            transaction_id=transaction_id,
            status=TransactionStatus.BANK_REQUEST_SENT,
            message="Запрос отправлен в банк-эквайер",
            details={
                "bank": "simulated_bank",
                "request_time": datetime.utcnow().isoformat()
            },
            order_id=payment_request.order_id,
            customer_id=payment_request.customer_id
        )
        
        # Имитация ответа от банка
        bank_response = {
            "bank_transaction_id": f"BANK_{uuid.uuid4().hex[:10]}",
            "status": "approved",
            "response_code": "00",
            "response_time": datetime.utcnow().isoformat()
        }
        
        # 5. Получение ответа от банка
        logger_service.log_transaction(
            transaction_id=transaction_id,
            status=TransactionStatus.BANK_RESPONSE_RECEIVED,
            message="Получен ответ от банка",
            details=bank_response,
            order_id=payment_request.order_id,
            customer_id=payment_request.customer_id
        )
        
        # 6. Успешное завершение транзакции
        logger_service.log_transaction(
            transaction_id=transaction_id,
            status=TransactionStatus.COMPLETED,
            message="Транзакция успешно завершена",
            details={
                "bank_transaction_id": bank_response["bank_transaction_id"],
                "final_amount": payment_request.amount,
                "commission": payment_request.amount * 0.02
            },
            order_id=payment_request.order_id,
            customer_id=payment_request.customer_id
        )
        
        return {
            "transaction_id": transaction_id,
            "status": "success",
            "message": "Платеж успешно обработан",
            "bank_transaction_id": bank_response["bank_transaction_id"],
            "amount": payment_request.amount,
            "currency": payment_request.currency,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        # Логирование ошибки
        logger_service.log_transaction(
            transaction_id=transaction_id,
            status=TransactionStatus.FAILED,
            message=f"Ошибка при обработке транзакции: {str(e)}",
            details={
                "error_type": type(e).__name__,
                "error_message": str(e)
            },
            order_id=payment_request.order_id if 'payment_request' in locals() else None,
            customer_id=payment_request.customer_id if 'payment_request' in locals() else None
        )
        
        raise HTTPException(
            status_code=500,
            detail={
                "transaction_id": transaction_id,
                "error": "Internal server error",
                "message": "Платеж не был обработан"
            }
        )

@app.get("/api/v1/transactions/{transaction_id}/logs")
async def get_transaction_logs(
    transaction_id: str,
    db: Session = Depends(get_db)
):
    """
    Эндпоинт для получения логов транзакции
    """
    logs = db.query(TransactionLogDB).filter(
        TransactionLogDB.transaction_id == transaction_id
    ).order_by(TransactionLogDB.timestamp).all()
    
    if not logs:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    
    return {
        "transaction_id": transaction_id,
        "logs": [
            {
                "id": log.id,
                "status": log.status.value,
                "message": log.message,
                "details": log.details,
                "timestamp": log.timestamp.isoformat(),
                "order_id": log.order_id,
                "customer_id": log.customer_id
            }
            for log in logs
        ]
    }

@app.get("/health")
async def health_check():
    """Эндпоинт для проверки здоровья сервиса"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "payment-transaction-logger"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)