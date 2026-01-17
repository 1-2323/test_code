from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
import logging
from abc import ABC, abstractmethod
import uuid

logger = logging.getLogger(__name__)


class PaymentStatus(str, Enum):
    """Статусы платежа."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentMethod(str, Enum):
    """Методы оплаты."""
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    PAYPAL = "paypal"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"


@dataclass
class Payment:
    """Платеж."""
    id: str
    amount: float
    currency: str = "RUB"
    user_id: str
    order_id: Optional[str] = None
    payment_method: PaymentMethod = PaymentMethod.CARD
    status: PaymentStatus = PaymentStatus.PENDING
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    paid_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    external_id: Optional[str] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'id': self.id,
            'amount': self.amount,
            'currency': self.currency,
            'user_id': self.user_id,
            'order_id': self.order_id,
            'payment_method': self.payment_method.value,
            'status': self.status.value,
            'description': self.description,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'refunded_at': self.refunded_at.isoformat() if self.refunded_at else None,
            'external_id': self.external_id,
            'error_message': self.error_message
        }


class PaymentGateway(ABC):
    """Базовый класс платежного шлюза."""
    
    @abstractmethod
    def create_payment(self, payment: Payment) -> Dict[str, Any]:
        """Создание платежа в шлюзе."""
        pass
    
    @abstractmethod
    def check_status(self, payment_id: str) -> PaymentStatus:
        """Проверка статуса платежа."""
        pass
    
    @abstractmethod
    def refund(self, payment_id: str, amount: Optional[float] = None) -> bool:
        """Возврат платежа."""
        pass
    
    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Верификация вебхука."""
        pass


class StripeGateway(PaymentGateway):
    """Шлюз Stripe."""
    
    def __init__(self, api_key: str, webhook_secret: str):
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        import stripe
        stripe.api_key = api_key
        self.client = stripe
    
    def create_payment(self, payment: Payment) -> Dict[str, Any]:
        try:
            intent = self.client.PaymentIntent.create(
                amount=int(payment.amount * 100),
                currency=payment.currency.lower(),
                description=payment.description,
                metadata={
                    'user_id': payment.user_id,
                    'order_id': payment.order_id or ''
                }
            )
            return {
                'client_secret': intent.client_secret,
                'payment_intent_id': intent.id
            }
        except Exception as e:
            logger.error(f"Stripe payment creation failed: {e}")
            raise
    
    def check_status(self, payment_id: str) -> PaymentStatus:
        try:
            intent = self.client.PaymentIntent.retrieve(payment_id)
            
            status_map = {
                'requires_payment_method': PaymentStatus.PENDING,
                'requires_confirmation': PaymentStatus.PROCESSING,
                'processing': PaymentStatus.PROCESSING,
                'requires_action': PaymentStatus.PROCESSING,
                'succeeded': PaymentStatus.SUCCESS,
                'canceled': PaymentStatus.CANCELLED
            }
            
            return status_map.get(intent.status, PaymentStatus.FAILED)
        except Exception as e:
            logger.error(f"Stripe status check failed: {e}")
            return PaymentStatus.FAILED
    
    def refund(self, payment_id: str, amount: Optional[float] = None) -> bool:
        try:
            refund_params = {'payment_intent': payment_id}
            if amount:
                refund_params['amount'] = int(amount * 100)
            
            self.client.Refund.create(**refund_params)
            return True
        except Exception as e:
            logger.error(f"Stripe refund failed: {e}")
            return False
    
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        try:
            from stripe import Webhook
            event = Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            return bool(event)
        except Exception as e:
            logger.error(f"Stripe webhook verification failed: {e}")
            return False


class PaymentStorage:
    """Хранилище платежей."""
    
    def __init__(self, db_path: str = "payments.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id TEXT PRIMARY KEY,
                    amount REAL NOT NULL,
                    currency TEXT DEFAULT 'RUB',
                    user_id TEXT NOT NULL,
                    order_id TEXT,
                    payment_method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    description TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    paid_at TIMESTAMP,
                    refunded_at TIMESTAMP,
                    external_id TEXT,
                    error_message TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON payments(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON payments(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_external_id ON payments(external_id)")
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def save(self, payment: Payment) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO payments VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, (
                    payment.id,
                    payment.amount,
                    payment.currency,
                    payment.user_id,
                    payment.order_id,
                    payment.payment_method.value,
                    payment.status.value,
                    payment.description,
                    json.dumps(payment.metadata),
                    payment.created_at,
                    payment.updated_at,
                    payment.paid_at,
                    payment.refunded_at,
                    payment.external_id,
                    payment.error_message
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving payment: {e}")
            return False
    
    def get(self, payment_id: str) -> Optional[Payment]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM payments WHERE id = ?",
                    (payment_id,)
                )
                row = cursor.fetchone()
                if row:
                    return Payment(
                        id=row['id'],
                        amount=row['amount'],
                        currency=row['currency'],
                        user_id=row['user_id'],
                        order_id=row['order_id'],
                        payment_method=PaymentMethod(row['payment_method']),
                        status=PaymentStatus(row['status']),
                        description=row['description'],
                        metadata=json.loads(row['metadata']) if row['metadata'] else {},
                        created_at=datetime.fromisoformat(row['created_at']),
                        updated_at=datetime.fromisoformat(row['updated_at']),
                        paid_at=datetime.fromisoformat(row['paid_at']) if row['paid_at'] else None,
                        refunded_at=datetime.fromisoformat(row['refunded_at']) if row['refunded_at'] else None,
                        external_id=row['external_id'],
                        error_message=row['error_message']
                    )
        except Exception as e:
            logger.error(f"Error getting payment: {e}")
        return None
    
    def update_status(self, payment_id: str, status: PaymentStatus,
                     external_id: Optional[str] = None,
                     error_message: Optional[str] = None) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                updates = []
                params = []
                
                updates.append("status = ?")
                params.append(status.value)
                
                updates.append("updated_at = ?")
                params.append(datetime.now().isoformat())
                
                if status == PaymentStatus.SUCCESS:
                    updates.append("paid_at = ?")
                    params.append(datetime.now().isoformat())
                
                if status == PaymentStatus.REFUNDED:
                    updates.append("refunded_at = ?")
                    params.append(datetime.now().isoformat())
                
                if external_id:
                    updates.append("external_id = ?")
                    params.append(external_id)
                
                if error_message:
                    updates.append("error_message = ?")
                    params.append(error_message)
                
                params.append(payment_id)
                cursor.execute(
                    f"UPDATE payments SET {', '.join(updates)} WHERE id = ?",
                    params
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating payment status: {e}")
            return False


class PaymentProcessor:
    """Обработчик платежей."""
    
    def __init__(self, gateway: PaymentGateway, storage: Optional[PaymentStorage] = None):
        self.gateway = gateway
        self.storage = storage or PaymentStorage()
    
    def create_payment(self, amount: float, user_id: str,
                      order_id: Optional[str] = None,
                      description: Optional[str] = None,
                      currency: str = "RUB",
                      metadata: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """Создание нового платежа."""
        payment_id = str(uuid.uuid4())
        
        payment = Payment(
            id=payment_id,
            amount=amount,
            currency=currency,
            user_id=user_id,
            order_id=order_id,
            description=description,
            metadata=metadata or {}
        )
        
        # Сохраняем в БД
        if not self.storage.save(payment):
            return None
        
        try:
            # Создаем платеж в шлюзе
            gateway_response = self.gateway.create_payment(payment)
            
            # Обновляем external_id
            if 'payment_intent_id' in gateway_response:
                payment.external_id = gateway_response['payment_intent_id']
                self.storage.save(payment)
            
            return {
                'payment_id': payment_id,
                'gateway_response': gateway_response
            }
            
        except Exception as e:
            logger.error(f"Payment creation failed: {e}")
            self.storage.update_status(
                payment_id,
                PaymentStatus.FAILED,
                error_message=str(e)
            )
            return None
    
    def check_payment(self, payment_id: str) -> Optional[Payment]:
        """Проверка статуса платежа."""
        payment = self.storage.get(payment_id)
        if not payment:
            return None
        
        # Если платеж уже завершен, возвращаем его
        if payment.status in [PaymentStatus.SUCCESS, PaymentStatus.FAILED, 
                            PaymentStatus.CANCELLED, PaymentStatus.REFUNDED]:
            return payment
        
        # Проверяем статус в шлюзе
        if payment.external_id:
            try:
                gateway_status = self.gateway.check_status(payment.external_id)
                
                # Обновляем статус если изменился
                if gateway_status != payment.status:
                    self.storage.update_status(payment_id, gateway_status)
                    payment.status = gateway_status
                
                return payment
                
            except Exception as e:
                logger.error(f"Payment status check failed: {e}")
        
        return payment
    
    def process_webhook(self, payload: bytes, signature: str) -> bool:
        """Обработка вебхука от платежного шлюза."""
        # Верифицируем подпись
        if not self.gateway.verify_webhook(payload, signature):
            logger.error("Webhook signature verification failed")
            return False
        
        try:
            event_data = json.loads(payload.decode('utf-8'))
            
            # Обрабатываем разные типы событий
            event_type = event_data.get('type')
            data = event_data.get('data', {})
            object_data = data.get('object', {})
            
            payment_intent_id = object_data.get('id')
            if not payment_intent_id:
                return False
            
            # Находим платеж по external_id
            payment = None
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM payments WHERE external_id = ?",
                    (payment_intent_id,)
                )
                row = cursor.fetchone()
                if row:
                    payment = self.storage.get(row['id'])
            
            if not payment:
                logger.warning(f"Payment not found for external_id: {payment_intent_id}")
                return False
            
            # Обновляем статус в зависимости от события
            if event_type == 'payment_intent.succeeded':
                self.storage.update_status(
                    payment.id, 
                    PaymentStatus.SUCCESS
                )
                logger.info(f"Payment {payment.id} marked as successful")
                
            elif event_type == 'payment_intent.payment_failed':
                error_message = object_data.get('last_payment_error', {}).get('message')
                self.storage.update_status(
                    payment.id,
                    PaymentStatus.FAILED,
                    error_message=error_message
                )
                logger.info(f"Payment {payment.id} marked as failed")
            
            return True
            
        except Exception as e:
            logger.error(f"Webhook processing failed: {e}")
            return False
    
    def refund_payment(self, payment_id: str, 
                      amount: Optional[float] = None) -> bool:
        """Возврат платежа."""
        payment = self.storage.get(payment_id)
        if not payment:
            logger.error(f"Payment not found: {payment_id}")
            return False
        
        if payment.status != PaymentStatus.SUCCESS:
            logger.error(f"Payment {payment_id} is not successful")
            return False
        
        if not payment.external_id:
            logger.error(f"No external_id for payment {payment_id}")
            return False
        
        try:
            # Выполняем возврат в шлюзе
            success = self.gateway.refund(payment.external_id, amount)
            
            if success:
                self.storage.update_status(
                    payment_id,
                    PaymentStatus.REFUNDED
                )
                logger.info(f"Payment {payment_id} refunded successfully")
            
            return success
            
        except Exception as e:
            logger.error(f"Refund failed: {e}")
            return False