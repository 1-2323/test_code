import requests
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging
from threading import Timer
import queue

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PaymentStatus(Enum):
    """Статусы платежа"""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class PaymentRequest:
    """Запрос на платеж"""
    amount: float
    currency: str
    order_id: str
    card_number: str
    card_expiry: str
    card_cvv: str
    description: Optional[str] = None


@dataclass
class PaymentResponse:
    """Ответ от платежного шлюза"""
    transaction_id: Optional[str]
    status: PaymentStatus
    gateway_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    is_timeout: bool = False


class PaymentGatewayError(Exception):
    """Исключение платежного шлюза"""
    pass


class PaymentTimeoutError(PaymentGatewayError):
    """Исключение таймаута платежа"""
    pass


class SecurePaymentGatewayClient:
    """
    Безопасный клиент платежного шлюза с обработкой таймаутов
    и гарантией идемпотентности
    """
    
    def __init__(self, gateway_url: str, api_key: str, timeout: int = 30):
        """
        Инициализация клиента платежного шлюза
        
        Args:
            gateway_url: URL платежного шлюза
            api_key: API ключ для аутентификации
            timeout: таймаут запроса в секундах
        """
        self.gateway_url = gateway_url
        self.api_key = api_key
        self.timeout = timeout
        self._pending_transactions: Dict[str, PaymentResponse] = {}
        
    def process_payment(self, payment_request: PaymentRequest) -> PaymentResponse:
        """
        Обработка платежа с гарантией защиты от таймаутов
        
        Args:
            payment_request: запрос на платеж
            
        Returns:
            Ответ платежного шлюза
            
        Raises:
            PaymentTimeoutError: если превышен таймаут
            PaymentGatewayError: при других ошибках шлюза
        """
        logger.info(f"Обработка платежа для заказа {payment_request.order_id}")
        
        # Создаем очередь для получения результата из потока
        result_queue = queue.Queue(maxsize=1)
        
        # Создаем и запускаем поток для обработки платежа
        import threading
        payment_thread = threading.Thread(
            target=self._process_payment_thread,
            args=(payment_request, result_queue)
        )
        payment_thread.daemon = True
        payment_thread.start()
        
        try:
            # Ожидаем результат с таймаутом
            response = result_queue.get(timeout=self.timeout)
            
            if response.is_timeout:
                logger.error(f"Таймаут платежа для заказа {payment_request.order_id}")
                # Важно: при таймауте считаем платеж НЕ успешным
                response.status = PaymentStatus.TIMEOUT
                raise PaymentTimeoutError(
                    f"Таймаут платежа. Платеж НЕ считается успешным для заказа {payment_request.order_id}"
                )
            
            return response
            
        except queue.Empty:
            # Таймаут при ожидании результата
            logger.error(f"Таймаут при обработке платежа для заказа {payment_request.order_id}")
            
            # Создаем ответ с таймаутом
            timeout_response = PaymentResponse(
                transaction_id=None,
                status=PaymentStatus.TIMEOUT,
                error_message=f"Таймаут платежа ({self.timeout} секунд)",
                is_timeout=True
            )
            
            # Сохраняем информацию о таймауте
            self._pending_transactions[payment_request.order_id] = timeout_response
            
            raise PaymentTimeoutError(
                f"Таймаут платежа. Статус платежа для заказа {payment_request.order_id} неизвестен"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при обработке платежа: {e}")
            raise PaymentGatewayError(f"Ошибка платежного шлюза: {e}")
    
    def _process_payment_thread(self, payment_request: PaymentRequest, 
                               result_queue: queue.Queue) -> None:
        """
        Обработка платежа в отдельном потоке
        
        Args:
            payment_request: запрос на платеж
            result_queue: очередь для возврата результата
        """
        try:
            # Отправляем запрос к платежному шлюзу
            response = self._send_payment_request(payment_request)
            
            # Помещаем результат в очередь
            result_queue.put(response, block=False)
            
        except Exception as e:
            # В случае ошибки возвращаем ответ с ошибкой
            error_response = PaymentResponse(
                transaction_id=None,
                status=PaymentStatus.FAILED,
                error_message=str(e),
                is_timeout=False
            )
            result_queue.put(error_response, block=False)
    
    def _send_payment_request(self, payment_request: PaymentRequest) -> PaymentResponse:
        """
        Отправка запроса к платежному шлюзу
        
        Args:
            payment_request: запрос на платеж
            
        Returns:
            Ответ от платежного шлюза
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": payment_request.order_id  # Ключ идемпотентности
        }
        
        # Подготовка данных запроса (маскируем чувствительные данные)
        request_data = {
            "amount": payment_request.amount,
            "currency": payment_request.currency,
            "order_id": payment_request.order_id,
            "card_number": self._mask_card_number(payment_request.card_number),
            "card_expiry": payment_request.card_expiry,
            "card_cvv": "***",  # CVV никогда не логируем
            "description": payment_request.description
        }
        
        try:
            logger.info(f"Отправка платежа в шлюз для заказа {payment_request.order_id}")
            
            response = requests.post(
                f"{self.gateway_url}/api/v1/payments",
                json=request_data,
                headers=headers,
                timeout=self.timeout
            )
            
            # Обработка ответа
            if response.status_code == 200:
                response_data = response.json()
                
                if response_data.get("success", False):
                    logger.info(f"Платеж успешен для заказа {payment_request.order_id}")
                    return PaymentResponse(
                        transaction_id=response_data.get("transaction_id"),
                        status=PaymentStatus.SUCCESS,
                        gateway_response=response_data
                    )
                else:
                    logger.warning(f"Платеж отклонен для заказа {payment_request.order_id}")
                    return PaymentResponse(
                        transaction_id=response_data.get("transaction_id"),
                        status=PaymentStatus.FAILED,
                        gateway_response=response_data,
                        error_message=response_data.get("error_message")
                    )
                    
            elif response.status_code == 408 or response.status_code == 504:
                # Таймаут от шлюза
                logger.error(f"Таймаут от платежного шлюза для заказа {payment_request.order_id}")
                return PaymentResponse(
                    transaction_id=None,
                    status=PaymentStatus.TIMEOUT,
                    error_message="Таймаут платежного шлюза",
                    is_timeout=True
                )
                
            else:
                # Другие ошибки HTTP
                logger.error(f"Ошибка HTTP {response.status_code} от шлюза")
                return PaymentResponse(
                    transaction_id=None,
                    status=PaymentStatus.FAILED,
                    error_message=f"HTTP ошибка: {response.status_code}"
                )
                
        except requests.exceptions.Timeout:
            logger.error(f"Таймаут соединения с платежным шлюзом")
            return PaymentResponse(
                transaction_id=None,
                status=PaymentStatus.TIMEOUT,
                error_message="Таймаут соединения",
                is_timeout=True
            )
            
        except requests.exceptions.ConnectionError:
            logger.error(f"Ошибка соединения с платежным шлюзом")
            return PaymentResponse(
                transaction_id=None,
                status=PaymentStatus.FAILED,
                error_message="Ошибка соединения"
            )
            
        except Exception as e:
            logger.error(f"Неизвестная ошибка при отправке платежа: {e}")
            return PaymentResponse(
                transaction_id=None,
                status=PaymentStatus.FAILED,
                error_message=f"Внутренняя ошибка: {str(e)}"
            )
    
    def check_payment_status(self, order_id: str) -> PaymentResponse:
        """
        Проверка статуса платежа
        
        Args:
            order_id: ID заказа
            
        Returns:
            Текущий статус платежа
        """
        # Проверяем pending транзакции
        if order_id in self._pending_transactions:
            return self._pending_transactions[order_id]
        
        # Если нет в pending, запрашиваем у шлюза
        return self._query_payment_status(order_id)
    
    def _query_payment_status(self, order_id: str) -> PaymentResponse:
        """
        Запрос статуса платежа у шлюза
        
        Args:
            order_id: ID заказа
            
        Returns:
            Статус платежа
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{self.gateway_url}/api/v1/payments/{order_id}/status",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return PaymentResponse(
                    transaction_id=data.get("transaction_id"),
                    status=PaymentStatus(data.get("status", "unknown")),
                    gateway_response=data
                )
            else:
                return PaymentResponse(
                    transaction_id=None,
                    status=PaymentStatus.UNKNOWN,
                    error_message=f"Ошибка запроса статуса: {response.status_code}"
                )
                
        except Exception as e:
            return PaymentResponse(
                transaction_id=None,
                status=PaymentStatus.UNKNOWN,
                error_message=str(e)
            )
    
    def _mask_card_number(self, card_number: str) -> str:
        """
        Маскирование номера карты для логирования
        
        Args:
            card_number: номер карты
            
        Returns:
            Замаскированный номер карты
        """
        if len(card_number) > 4:
            return "**** **** **** " + card_number[-4:]
        return "****"


# Пример использования
def main():
    """Пример использования безопасного клиента платежного шлюза"""
    
    # Инициализация клиента
    payment_client = SecurePaymentGatewayClient(
        gateway_url="https://payment-gateway.example.com",
        api_key="your-api-key-here",
        timeout=15  # 15 секунд на обработку платежа
    )
    
    # Создание запроса на платеж
    payment_request = PaymentRequest(
        amount=100.50,
        currency="USD",
        order_id="ORDER-12345",
        card_number="4111111111111111",
        card_expiry="12/25",
        card_cvv="123",
        description="Оплата заказа #12345"
    )
    
    try:
        # Обработка платежа
        response = payment_client.process_payment(payment_request)
        
        # Анализ результата
        if response.status == PaymentStatus.SUCCESS:
            print(f"Платеж успешен! Transaction ID: {response.transaction_id}")
            # Помечаем заказ как оплаченный
            mark_order_as_paid(payment_request.order_id)
            
        elif response.status == PaymentStatus.TIMEOUT:
            # Критически важный случай: таймаут
            print("ВНИМАНИЕ: Таймаут платежа. Платеж НЕ считается успешным!")
            print("Необходимо проверить статус вручную или через систему мониторинга")
            
            # Важно: НЕ помечаем заказ как оплаченный при таймауте
            handle_payment_timeout(payment_request.order_id)
            
        else:
            print(f"Платеж не удался: {response.error_message}")
            handle_payment_failure(payment_request.order_id)
            
    except PaymentTimeoutError as e:
        # Обработка исключения таймаута
        print(f"Критическая ошибка: {e}")
        print("Платеж НЕ был выполнен из-за таймаута")
        
    except PaymentGatewayError as e:
        print(f"Ошибка платежного шлюза: {e}")


def mark_order_as_paid(order_id: str) -> None:
    """Пометить заказ как оплаченный"""
    print(f"Заказ {order_id} помечен как оплаченный")


def handle_payment_timeout(order_id: str) -> None:
    """Обработка таймаута платежа"""
    print(f"Таймаут платежа для заказа {order_id}. Требуется ручная проверка.")


def handle_payment_failure(order_id: str) -> None:
    """Обработка неудачи платежа"""
    print(f"Неудача платежа для заказа {order_id}")


if __name__ == "__main__":
    main()