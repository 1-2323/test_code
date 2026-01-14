import requests
import logging
from typing import Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass
import json

class PaymentStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    TIMEOUT = "timeout"
    ERROR = "error"

@dataclass
class PaymentResponse:
    status: PaymentStatus
    transaction_id: Optional[str] = None
    gateway_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

class PaymentGatewayClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        max_retries: int = 2,
        retry_delay: float = 1.0
    ):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.session = requests.Session()
        self.logger = self._setup_logger()
        
        # Конфигурация повторных попыток
        retry_adapter = requests.adapters.HTTPAdapter(
            max_retries=max_retries,
            pool_connections=10,
            pool_maxsize=10
        )
        self.session.mount('http://', retry_adapter)
        self.session.mount('https://', retry_adapter)
    
    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger
    
    def _handle_timeout(self, transaction_id: Optional[str] = None) -> PaymentResponse:
        self.logger.warning(
            f"Timeout occurred for transaction {transaction_id or 'unknown'}"
        )
        return PaymentResponse(
            status=PaymentStatus.TIMEOUT,
            transaction_id=transaction_id,
            error_message="Payment gateway timeout"
        )
    
    def _handle_request_exception(
        self,
        exception: Exception,
        transaction_id: Optional[str] = None
    ) -> PaymentResponse:
        self.logger.error(
            f"Request exception for transaction {transaction_id or 'unknown'}: {str(exception)}"
        )
        return PaymentResponse(
            status=PaymentStatus.ERROR,
            transaction_id=transaction_id,
            error_message=f"Gateway communication error: {str(exception)}"
        )
    
    def _validate_gateway_response(self, response_data: Dict[str, Any]) -> bool:
        """Валидация ответа от платежного шлюза"""
        if not isinstance(response_data, dict):
            self.logger.error("Gateway response is not a dictionary")
            return False
        
        # Проверяем наличие обязательных полей
        required_fields = ['status', 'transaction_id']
        for field in required_fields:
            if field not in response_data:
                self.logger.error(f"Missing required field in gateway response: {field}")
                return False
        
        # Проверяем статус транзакции
        valid_statuses = ['success', 'failed', 'pending', 'error']
        if response_data.get('status') not in valid_statuses:
            self.logger.error(f"Invalid status in gateway response: {response_data.get('status')}")
            return False
        
        return True
    
    def _parse_gateway_response(self, response: requests.Response) -> PaymentResponse:
        """Парсинг и валидация ответа от шлюза"""
        try:
            response_data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"Failed to parse gateway response: {str(e)}")
            return PaymentResponse(
                status=PaymentStatus.ERROR,
                error_message="Invalid response format from payment gateway"
            )
        
        # Валидируем структуру ответа
        if not self._validate_gateway_response(response_data):
            return PaymentResponse(
                status=PaymentStatus.ERROR,
                error_message="Invalid gateway response structure"
            )
        
        # Маппинг статуса
        status_mapping = {
            'success': PaymentStatus.SUCCESS,
            'failed': PaymentStatus.FAILED,
            'pending': PaymentStatus.PENDING,
            'error': PaymentStatus.ERROR
        }
        
        gateway_status = response_data.get('status', 'error')
        status = status_mapping.get(gateway_status, PaymentStatus.ERROR)
        
        # Для успешного статуса требуется дополнительная проверка
        if status == PaymentStatus.SUCCESS:
            # Здесь можно добавить дополнительные проверки для успешного платежа
            # Например, проверку подписи, суммы, валюты и т.д.
            if not self._validate_successful_payment(response_data):
                status = PaymentStatus.ERROR
                response_data['status'] = 'error'
                response_data['error'] = 'Payment validation failed'
        
        return PaymentResponse(
            status=status,
            transaction_id=response_data.get('transaction_id'),
            gateway_response=response_data,
            error_message=response_data.get('error_message') or response_data.get('error')
        )
    
    def _validate_successful_payment(self, response_data: Dict[str, Any]) -> bool:
        """Дополнительная валидация для успешных платежей"""
        # Здесь можно реализовать:
        # 1. Проверку цифровой подписи
        # 2. Проверку соответствия суммы
        # 3. Проверку валюты
        # 4. Проверку получателя
        # 5. Проверку кода авторизации и т.д.
        
        # Минимальная проверка - наличие transaction_id
        transaction_id = response_data.get('transaction_id')
        if not transaction_id or not isinstance(transaction_id, str):
            self.logger.error("Invalid transaction_id in successful payment")
            return False
        
        # Проверяем, что нет ошибок в ответе при успешном статусе
        if response_data.get('error') or response_data.get('error_message'):
            self.logger.error("Error fields present in successful payment response")
            return False
        
        return True
    
    def process_payment_callback(
        self,
        callback_data: Dict[str, Any],
        endpoint: str = "/api/payment/callback"
    ) -> PaymentResponse:
        """
        Обработка callback от платежного шлюза
        
        Args:
            callback_data: Данные callback от шлюза
            endpoint: Endpoint для отправки подтверждения
            
        Returns:
            PaymentResponse: Результат обработки платежа
        """
        transaction_id = callback_data.get('transaction_id')
        
        try:
            # Логируем получение callback
            self.logger.info(
                f"Processing payment callback for transaction: {transaction_id}"
            )
            
            # Отправляем подтверждение получения callback
            response = self.session.post(
                f"{self.base_url}{endpoint}",
                json=callback_data,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            # Парсим ответ от шлюза
            payment_response = self._parse_gateway_response(response)
            
            # Дополнительная обработка для таймаутов и ошибок
            if payment_response.status in [PaymentStatus.TIMEOUT, PaymentStatus.ERROR]:
                self.logger.error(
                    f"Payment gateway returned error status: {payment_response.status.value} "
                    f"for transaction: {transaction_id}"
                )
            
            return payment_response
            
        except requests.exceptions.Timeout:
            return self._handle_timeout(transaction_id)
            
        except requests.exceptions.RequestException as e:
            return self._handle_request_exception(e, transaction_id)
            
        except Exception as e:
            self.logger.error(
                f"Unexpected error processing payment callback for "
                f"transaction {transaction_id}: {str(e)}"
            )
            return PaymentResponse(
                status=PaymentStatus.ERROR,
                transaction_id=transaction_id,
                error_message=f"Unexpected error: {str(e)}"
            )
    
    def check_payment_status(
        self,
        transaction_id: str,
        endpoint: str = "/api/payment/status"
    ) -> PaymentResponse:
        """
        Проверка статуса платежа
        
        Args:
            transaction_id: Идентификатор транзакции
            endpoint: Endpoint для проверки статуса
            
        Returns:
            PaymentResponse: Результат проверки статуса
        """
        try:
            self.logger.info(f"Checking payment status for transaction: {transaction_id}")
            
            response = self.session.get(
                f"{self.base_url}{endpoint}/{transaction_id}",
                timeout=self.timeout
            )
            response.raise_for_status()
            
            return self._parse_gateway_response(response)
            
        except requests.exceptions.Timeout:
            return self._handle_timeout(transaction_id)
            
        except requests.exceptions.RequestException as e:
            return self._handle_request_exception(e, transaction_id)
            
        except Exception as e:
            self.logger.error(
                f"Unexpected error checking payment status for "
                f"transaction {transaction_id}: {str(e)}"
            )
            return PaymentResponse(
                status=PaymentStatus.ERROR,
                transaction_id=transaction_id,
                error_message=f"Unexpected error: {str(e)}"
            )
    
    def close(self):
        """Закрытие клиента и освобождение ресурсов"""
        self.session.close()
        self.logger.info("Payment gateway client closed")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

# Пример использования (закомментирован, как просили без примеров):
"""
# Инициализация клиента
gateway_client = PaymentGatewayClient(
    base_url="https://api.payment-gateway.com",
    timeout=15.0,
    max_retries=3
)

# Обработка callback
callback_data = {
    "transaction_id": "txn_123456",
    "status": "success",
    "amount": 100.0,
    "currency": "USD"
}

result = gateway_client.process_payment_callback(callback_data)

if result.status == PaymentStatus.SUCCESS:
    print(f"Payment successful: {result.transaction_id}")
else:
    print(f"Payment failed: {result.error_message}")
"""