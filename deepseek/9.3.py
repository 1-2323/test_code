import logging
import uuid
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, field
from enum import Enum
from functools import wraps
import time

from flask import Flask, request, jsonify, g, Response
from pydantic import BaseModel, validator, Field
from sqlalchemy import create_engine, Column, String, DateTime, JSON, Text, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func
import redis
from kafka import KafkaProducer
import pika

# Настройка основного логгера
logger = logging.getLogger('payment_processor')
logger.setLevel(logging.INFO)

# Форматирование логов
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Файловый обработчик
file_handler = logging.FileHandler('payment_transactions.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Консольный обработчик
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# JSON логгер
json_logger = logging.getLogger('payment_json_logger')
json_logger.setLevel(logging.INFO)
json_handler = logging.FileHandler('payment_transactions.json')
json_handler.setFormatter(logging.Formatter('%(message)s'))
json_logger.addHandler(json_handler)

# Настройка базы данных для логирования
DATABASE_URL = "sqlite:///payment_transactions.db"
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TransactionStatus(Enum):
    """Статусы транзакции"""
    INITIATED = "INITIATED"
    VALIDATING = "VALIDATING"
    PROCESSING = "PROCESSING"
    AUTHORIZING = "AUTHORIZING"
    CAPTURING = "CAPTURING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    PENDING = "PENDING"


class TransactionType(Enum):
    """Типы транзакций"""
    PURCHASE = "PURCHASE"
    REFUND = "REFUND"
    AUTH_ONLY = "AUTH_ONLY"
    CAPTURE = "CAPTURE"
    VOID = "VOID"
    SUBSCRIPTION = "SUBSCRIPTION"
    RECURRING = "RECURRING"


class TransactionLog(Base):
    """Модель для хранения логов транзакций в БД"""
    __tablename__ = "transaction_logs"

    id = Column(String(36), primary_key=True, index=True)
    transaction_id = Column(String(36), nullable=False, index=True)
    parent_transaction_id = Column(String(36), nullable=True, index=True)
    correlation_id = Column(String(36), nullable=True, index=True)
    
    status = Column(SQLEnum(TransactionStatus), nullable=False)
    transaction_type = Column(SQLEnum(TransactionType), nullable=False)
    
    amount = Column(String(20), nullable=False)
    currency = Column(String(3), nullable=False)
    
    merchant_id = Column(String(50), nullable=False, index=True)
    customer_id = Column(String(50), nullable=True, index=True)
    payment_method = Column(String(50), nullable=True)
    
    request_data = Column(JSON, nullable=True)
    response_data = Column(JSON, nullable=True)
    error_details = Column(JSON, nullable=True)
    
    gateway = Column(String(50), nullable=True)
    gateway_transaction_id = Column(String(100), nullable=True)
    
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    metadata = Column(JSON, nullable=True)
    processing_time_ms = Column(String(20), nullable=True)


# Создание таблиц
Base.metadata.create_all(bind=engine)


@dataclass
class TransactionEvent:
    """Событие транзакции для логирования"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    transaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_transaction_id: Optional[str] = None
    correlation_id: Optional[str] = None
    
    status: TransactionStatus = TransactionStatus.INITIATED
    transaction_type: TransactionType = TransactionType.PURCHASE
    
    amount: str = "0.00"
    currency: str = "USD"
    
    merchant_id: str = ""
    customer_id: Optional[str] = None
    payment_method: Optional[str] = None
    
    request_data: Optional[Dict[str, Any]] = None
    response_data: Optional[Dict[str, Any]] = None
    error_details: Optional[Dict[str, Any]] = None
    
    gateway: Optional[str] = None
    gateway_transaction_id: Optional[str] = None
    
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_time_ms: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        data = asdict(self)
        data['status'] = self.status.value
        data['transaction_type'] = self.transaction_type.value
        data['timestamp'] = self.timestamp.isoformat()
        return data


class PaymentRequest(BaseModel):
    """Pydantic модель для входящего запроса на платеж"""
    amount: float = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field("USD", max_length=3, description="Валюта")
    merchant_id: str = Field(..., description="ID мерчанта")
    customer_id: Optional[str] = Field(None, description="ID клиента")
    payment_method: str = Field(..., description="Метод оплаты")
    payment_method_details: Dict[str, Any] = Field(default_factory=dict)
    
    order_id: Optional[str] = None
    description: Optional[str] = None
    
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    
    billing_address: Optional[Dict[str, Any]] = None
    shipping_address: Optional[Dict[str, Any]] = None
    
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('amount')
    def validate_amount(cls, v):
        """Валидация суммы"""
        if v <= 0:
            raise ValueError('Amount must be greater than 0')
        return round(v, 2)
    
    @validator('currency')
    def validate_currency(cls, v):
        """Валидация валюты"""
        if len(v) != 3:
            raise ValueError('Currency must be 3 characters')
        return v.upper()


class TransactionLogger:
    """Класс для логирования транзакций"""
    
    def __init__(self, db_session: Session, use_redis: bool = False, 
                 use_kafka: bool = False, use_rabbitmq: bool = False):
        self.db_session = db_session
        self.use_redis = use_redis
        self.use_kafka = use_kafka
        self.use_rabbitmq = use_rabbitmq
        
        # Инициализация Redis
        if use_redis:
            self.redis_client = redis.Redis(
                host='localhost',
                port=6379,
                db=0,
                decode_responses=True
            )
        
        # Инициализация Kafka
        if use_kafka:
            self.kafka_producer = KafkaProducer(
                bootstrap_servers=['localhost:9092'],
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
        
        # Инициализация RabbitMQ
        if use_rabbitmq:
            self.rabbit_connection = pika.BlockingConnection(
                pika.ConnectionParameters('localhost')
            )
            self.rabbit_channel = self.rabbit_connection.channel()
            self.rabbit_channel.queue_declare(queue='payment_transactions')
    
    def log_event(self, event: TransactionEvent) -> None:
        """Логирование события транзакции"""
        # 1. Логирование в файл (структурированное)
        self._log_to_file(event)
        
        # 2. Логирование в базу данных
        self._log_to_database(event)
        
        # 3. Логирование в Redis для быстрого доступа
        if self.use_redis:
            self._log_to_redis(event)
        
        # 4. Отправка в Kafka для обработки в реальном времени
        if self.use_kafka:
            self._send_to_kafka(event)
        
        # 5. Отправка в RabbitMQ для асинхронной обработки
        if self.use_rabbitmq:
            self._send_to_rabbitmq(event)
    
    def _log_to_file(self, event: TransactionEvent) -> None:
        """Логирование в текстовый файл"""
        log_message = (
            f"Transaction Event - ID: {event.transaction_id}, "
            f"Status: {event.status.value}, "
            f"Type: {event.transaction_type.value}, "
            f"Amount: {event.amount} {event.currency}, "
            f"Merchant: {event.merchant_id}"
        )
        
        if event.error_details:
            log_message += f", Error: {event.error_details}"
        
        if event.status == TransactionStatus.SUCCESS:
            logger.info(log_message)
        elif event.status == TransactionStatus.FAILED:
            logger.error(log_message)
        else:
            logger.debug(log_message)
        
        # JSON логирование
        json_logger.info(json.dumps(event.to_dict()))
    
    def _log_to_database(self, event: TransactionEvent) -> None:
        """Сохранение лога в базу данных"""
        try:
            db_log = TransactionLog(
                id=event.event_id,
                transaction_id=event.transaction_id,
                parent_transaction_id=event.parent_transaction_id,
                correlation_id=event.correlation_id,
                status=event.status,
                transaction_type=event.transaction_type,
                amount=str(event.amount),
                currency=event.currency,
                merchant_id=event.merchant_id,
                customer_id=event.customer_id,
                payment_method=event.payment_method,
                request_data=event.request_data,
                response_data=event.response_data,
                error_details=event.error_details,
                gateway=event.gateway,
                gateway_transaction_id=event.gateway_transaction_id,
                ip_address=event.ip_address,
                user_agent=event.user_agent,
                metadata=event.metadata,
                processing_time_ms=str(event.processing_time_ms) if event.processing_time_ms else None
            )
            
            self.db_session.add(db_log)
            self.db_session.commit()
            
        except Exception as e:
            logger.error(f"Failed to log transaction to database: {e}")
            self.db_session.rollback()
    
    def _log_to_redis(self, event: TransactionEvent) -> None:
        """Кэширование транзакции в Redis"""
        try:
            key = f"transaction:{event.transaction_id}"
            data = event.to_dict()
            
            # Сохранение в Redis с TTL 24 часа
            self.redis_client.hset(key, mapping=data)
            self.redis_client.expire(key, 86400)
            
            # Сохранение в sorted set для быстрого поиска по времени
            self.redis_client.zadd(
                "transactions:timeline",
                {event.transaction_id: event.timestamp.timestamp()}
            )
            
        except Exception as e:
            logger.error(f"Failed to log transaction to Redis: {e}")
    
    def _send_to_kafka(self, event: TransactionEvent) -> None:
        """Отправка события в Kafka"""
        try:
            self.kafka_producer.send(
                'payment-transactions',
                value=event.to_dict()
            )
            self.kafka_producer.flush()
        except Exception as e:
            logger.error(f"Failed to send transaction to Kafka: {e}")
    
    def _send_to_rabbitmq(self, event: TransactionEvent) -> None:
        """Отправка события в RabbitMQ"""
        try:
            self.rabbit_channel.basic_publish(
                exchange='',
                routing_key='payment_transactions',
                body=json.dumps(event.to_dict()),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # persistent message
                    content_type='application/json'
                )
            )
        except Exception as e:
            logger.error(f"Failed to send transaction to RabbitMQ: {e}")
    
    def get_transaction_history(self, transaction_id: str) -> List[TransactionEvent]:
        """Получение истории транзакции"""
        try:
            logs = self.db_session.query(TransactionLog).filter(
                TransactionLog.transaction_id == transaction_id
            ).order_by(TransactionLog.created_at).all()
            
            events = []
            for log in logs:
                event = TransactionEvent(
                    event_id=log.id,
                    transaction_id=log.transaction_id,
                    parent_transaction_id=log.parent_transaction_id,
                    correlation_id=log.correlation_id,
                    status=log.status,
                    transaction_type=log.transaction_type,
                    amount=log.amount,
                    currency=log.currency,
                    merchant_id=log.merchant_id,
                    customer_id=log.customer_id,
                    payment_method=log.payment_method,
                    request_data=log.request_data,
                    response_data=log.response_data,
                    error_details=log.error_details,
                    gateway=log.gateway,
                    gateway_transaction_id=log.gateway_transaction_id,
                    ip_address=log.ip_address,
                    user_agent=log.user_agent,
                    timestamp=log.created_at,
                    metadata=log.metadata,
                    processing_time_ms=int(log.processing_time_ms) if log.processing_time_ms else None
                )
                events.append(event)
            
            return events
            
        except Exception as e:
            logger.error(f"Failed to get transaction history: {e}")
            return []


class PaymentProcessor:
    """Класс для обработки платежей"""
    
    def __init__(self, logger: TransactionLogger):
        self.logger = logger
    
    def process_payment(self, payment_request: PaymentRequest, 
                       correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """Основной метод обработки платежа"""
        start_time = time.time()
        transaction_id = str(uuid.uuid4())
        
        # Сбор информации о запросе
        ip_address = request.remote_addr if request else None
        user_agent = request.user_agent.string if request else None
        
        try:
            # 1. Инициация транзакции
            self._log_transaction_initiation(
                transaction_id, payment_request, ip_address, user_agent, correlation_id
            )
            
            # 2. Валидация данных
            self._log_transaction_status(transaction_id, TransactionStatus.VALIDATING)
            if not self._validate_payment_data(payment_request):
                raise ValueError("Invalid payment data")
            
            # 3. Обработка платежа
            self._log_transaction_status(transaction_id, TransactionStatus.PROCESSING)
            
            # 4. Авторизация в платежном шлюзе
            self._log_transaction_status(transaction_id, TransactionStatus.AUTHORIZING)
            auth_result = self._authorize_payment(payment_request)
            
            # 5. Захват средств
            self._log_transaction_status(transaction_id, TransactionStatus.CAPTURING)
            capture_result = self._capture_payment(auth_result, payment_request)
            
            # 6. Успешное завершение
            processing_time = int((time.time() - start_time) * 1000)
            self._log_transaction_success(
                transaction_id, capture_result, processing_time
            )
            
            return {
                "transaction_id": transaction_id,
                "status": "success",
                "gateway_transaction_id": capture_result.get("gateway_transaction_id"),
                "amount": payment_request.amount,
                "currency": payment_request.currency,
                "processing_time_ms": processing_time,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            # Логирование ошибки
            processing_time = int((time.time() - start_time) * 1000)
            self._log_transaction_failure(
                transaction_id, str(e), processing_time
            )
            
            raise
    
    def _log_transaction_initiation(self, transaction_id: str, 
                                  payment_request: PaymentRequest,
                                  ip_address: Optional[str],
                                  user_agent: Optional[str],
                                  correlation_id: Optional[str]):
        """Логирование инициации транзакции"""
        event = TransactionEvent(
            transaction_id=transaction_id,
            correlation_id=correlation_id,
            status=TransactionStatus.INITIATED,
            transaction_type=TransactionType.PURCHASE,
            amount=f"{payment_request.amount:.2f}",
            currency=payment_request.currency,
            merchant_id=payment_request.merchant_id,
            customer_id=payment_request.customer_id,
            payment_method=payment_request.payment_method,
            request_data=payment_request.dict(),
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=payment_request.metadata
        )
        
        self.logger.log_event(event)
    
    def _log_transaction_status(self, transaction_id: str, status: TransactionStatus):
        """Логирование изменения статуса транзакции"""
        event = TransactionEvent(
            transaction_id=transaction_id,
            status=status
        )
        
        self.logger.log_event(event)
    
    def _log_transaction_success(self, transaction_id: str, 
                               result: Dict[str, Any], 
                               processing_time: int):
        """Логирование успешной транзакции"""
        event = TransactionEvent(
            transaction_id=transaction_id,
            status=TransactionStatus.SUCCESS,
            response_data=result,
            gateway_transaction_id=result.get("gateway_transaction_id"),
            gateway=result.get("gateway"),
            processing_time_ms=processing_time
        )
        
        self.logger.log_event(event)
    
    def _log_transaction_failure(self, transaction_id: str, 
                               error_message: str, 
                               processing_time: int):
        """Логирование неудачной транзакции"""
        event = TransactionEvent(
            transaction_id=transaction_id,
            status=TransactionStatus.FAILED,
            error_details={"error": error_message},
            processing_time_ms=processing_time
        )
        
        self.logger.log_event(event)
    
    def _validate_payment_data(self, payment_request: PaymentRequest) -> bool:
        """Валидация данных платежа"""
        # Реализация валидации
        return True
    
    def _authorize_payment(self, payment_request: PaymentRequest) -> Dict[str, Any]:
        """Авторизация платежа через шлюз"""
        # Реализация авторизации
        return {
            "gateway_transaction_id": f"auth_{uuid.uuid4().hex[:16]}",
            "gateway": "test_gateway",
            "authorization_code": f"auth_{uuid.uuid4().hex[:8]}"
        }
    
    def _capture_payment(self, auth_result: Dict[str, Any], 
                        payment_request: PaymentRequest) -> Dict[str, Any]:
        """Захват средств"""
        # Реализация захвата средств
        return {
            **auth_result,
            "captured_amount": payment_request.amount,
            "capture_time": datetime.utcnow().isoformat()
        }


def transaction_logging_middleware(func):
    """Декоратор для логирования транзакций в эндпоинтах"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Получение или создание correlation_id
        correlation_id = request.headers.get('X-Correlation-ID') or str(uuid.uuid4())
        
        # Сохранение в контексте приложения
        g.correlation_id = correlation_id
        
        # Логирование входящего запроса
        logger.info(
            f"Incoming request - Path: {request.path}, "
            f"Method: {request.method}, "
            f"Correlation-ID: {correlation_id}"
        )
        
        try:
            response = func(*args, **kwargs)
            
            # Логирование успешного ответа
            logger.info(
                f"Request completed - Path: {request.path}, "
                f"Status: {response.status_code}, "
                f"Correlation-ID: {correlation_id}"
            )
            
            # Добавление correlation_id в заголовки ответа
            response.headers['X-Correlation-ID'] = correlation_id
            
            return response
            
        except Exception as e:
            # Логирование ошибки
            logger.error(
                f"Request failed - Path: {request.path}, "
                f"Error: {str(e)}, "
                f"Correlation-ID: {correlation_id}"
            )
            raise
    
    return wrapper


# Создание Flask приложения
app = Flask(__name__)


@app.before_request
def before_request():
    """Инициализация сессии БД перед запросом"""
    g.db_session = SessionLocal()
    g.logger = TransactionLogger(g.db_session)
    g.processor = PaymentProcessor(g.logger)


@app.teardown_request
def teardown_request(exception=None):
    """Закрытие сессии БД после запроса"""
    db_session = getattr(g, 'db_session', None)
    if db_session is not None:
        db_session.close()


@app.route('/api/v1/payments/process', methods=['POST'])
@transaction_logging_middleware
def process_payment():
    """Эндпоинт для обработки платежей"""
    try:
        # Валидация входящих данных
        payment_data = request.get_json()
        payment_request = PaymentRequest(**payment_data)
        
        # Получение correlation_id из заголовков или контекста
        correlation_id = getattr(g, 'correlation_id', None)
        
        # Обработка платежа
        result = g.processor.process_payment(payment_request, correlation_id)
        
        return jsonify({
            "success": True,
            "data": result,
            "correlation_id": correlation_id
        }), 200
        
    except Exception as e:
        logger.error(f"Payment processing error: {e}")
        
        return jsonify({
            "success": False,
            "error": str(e),
            "correlation_id": getattr(g, 'correlation_id', None)
        }), 400


@app.route('/api/v1/payments/<transaction_id>/status', methods=['GET'])
@transaction_logging_middleware
def get_transaction_status(transaction_id: str):
    """Эндпоинт для получения статуса транзакции"""
    try:
        # Получение истории транзакции
        events = g.logger.get_transaction_history(transaction_id)
        
        if not events:
            return jsonify({
                "success": False,
                "error": "Transaction not found"
            }), 404
        
        # Формирование ответа
        latest_event = events[-1]
        
        return jsonify({
            "success": True,
            "data": {
                "transaction_id": transaction_id,
                "status": latest_event.status.value,
                "amount": latest_event.amount,
                "currency": latest_event.currency,
                "merchant_id": latest_event.merchant_id,
                "created_at": latest_event.timestamp.isoformat(),
                "history": [
                    {
                        "status": event.status.value,
                        "timestamp": event.timestamp.isoformat(),
                        "error": event.error_details
                    }
                    for event in events
                ]
            },
            "correlation_id": getattr(g, 'correlation_id', None)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting transaction status: {e}")
        
        return jsonify({
            "success": False,
            "error": str(e),
            "correlation_id": getattr(g, 'correlation_id', None)
        }), 500


@app.route('/api/v1/payments/<transaction_id>/refund', methods=['POST'])
@transaction_logging_middleware
def refund_payment(transaction_id: str):
    """Эндпоинт для возврата платежа"""
    try:
        refund_data = request.get_json()
        amount = refund_data.get('amount')
        
        # Получение исходной транзакции
        events = g.logger.get_transaction_history(transaction_id)
        if not events:
            return jsonify({
                "success": False,
                "error": "Original transaction not found"
            }), 404
        
        original_event = events[-1]
        
        # Создание события возврата
        refund_event = TransactionEvent(
            transaction_id=str(uuid.uuid4()),
            parent_transaction_id=transaction_id,
            correlation_id=getattr(g, 'correlation_id', None),
            status=TransactionStatus.INITIATED,
            transaction_type=TransactionType.REFUND,
            amount=str(amount) if amount else original_event.amount,
            currency=original_event.currency,
            merchant_id=original_event.merchant_id,
            customer_id=original_event.customer_id,
            payment_method=original_event.payment_method,
            request_data=refund_data,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        
        # Логирование инициации возврата
        g.logger.log_event(refund_event)
        
        # Здесь должна быть логика обработки возврата
        
        # Логирование успешного возврата
        refund_event.status = TransactionStatus.SUCCESS
        refund_event.response_data = {"refund_id": str(uuid.uuid4())}
        g.logger.log_event(refund_event)
        
        return jsonify({
            "success": True,
            "data": {
                "refund_id": refund_event.transaction_id,
                "original_transaction_id": transaction_id,
                "amount": refund_event.amount,
                "status": "refunded"
            },
            "correlation_id": getattr(g, 'correlation_id', None)
        }), 200
        
    except Exception as e:
        logger.error(f"Refund processing error: {e}")
        
        return jsonify({
            "success": False,
            "error": str(e),
            "correlation_id": getattr(g, 'correlation_id', None)
        }), 400


@app.route('/api/v1/payments/health', methods=['GET'])
def health_check():
    """Эндпоинт для проверки здоровья сервиса"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "payment-processor"
    }), 200


@app.route('/api/v1/payments/logs/export', methods=['GET'])
def export_logs():
    """Эндпоинт для экспорта логов"""
    try:
        # Параметры запроса
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        merchant_id = request.args.get('merchant_id')
        status = request.args.get('status')
        
        # Формирование запроса
        query = g.db_session.query(TransactionLog)
        
        if start_date:
            query = query.filter(TransactionLog.created_at >= start_date)
        if end_date:
            query = query.filter(TransactionLog.created_at <= end_date)
        if merchant_id:
            query = query.filter(TransactionLog.merchant_id == merchant_id)
        if status:
            query = query.filter(TransactionLog.status == status)
        
        logs = query.order_by(TransactionLog.created_at.desc()).limit(1000).all()
        
        # Формирование CSV
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow([
            'transaction_id', 'status', 'amount', 'currency',
            'merchant_id', 'customer_id', 'created_at', 
            'gateway', 'error_details'
        ])
        
        # Данные
        for log in logs:
            writer.writerow([
                log.transaction_id,
                log.status.value,
                log.amount,
                log.currency,
                log.merchant_id,
                log.customer_id or '',
                log.created_at.isoformat(),
                log.gateway or '',
                str(log.error_details) if log.error_details else ''
            ])
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': 'attachment; filename=payment_logs.csv'
            }
        )
        
    except Exception as e:
        logger.error(f"Error exporting logs: {e}")
        
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == '__main__':
    # Настройка дополнительных обработчиков логов
    error_handler = logging.FileHandler('payment_errors.log')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    # Запуск приложения
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    )