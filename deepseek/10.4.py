import json
import time
import hmac
import hashlib
import logging
import asyncio
import aiohttp
import requests
from typing import Any, Dict, List, Optional, Union, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlencode
from decimal import Decimal
import ssl
import certifi

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PaymentStatus(Enum):
    """Статусы платежей."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    DECLINED = "declined"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

class PaymentMethod(Enum):
    """Методы оплаты."""
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    E_WALLET = "e_wallet"
    CRYPTO = "crypto"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"

class Currency(Enum):
    """Валюты."""
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    RUB = "RUB"
    CNY = "CNY"
    BTC = "BTC"
    ETH = "ETH"

@dataclass
class PaymentRequest:
    """Запрос на создание платежа."""
    amount: Decimal
    currency: Currency
    order_id: str
    description: str
    customer_email: str
    customer_ip: str
    return_url: str
    cancel_url: str
    callback_url: str
    payment_method: PaymentMethod
    metadata: Dict[str, Any] = field(default_factory=dict)
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    items: List[Dict[str, Any]] = field(default_factory=list)
    language: str = "en"

@dataclass
class PaymentResponse:
    """Ответ на создание платежа."""
    payment_id: str
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    order_id: str
    payment_url: Optional[str] = None
    qr_code_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    transaction_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

@dataclass
class PaymentWebhook:
    """Вебхук от платежной системы."""
    payment_id: str
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    order_id: str
    timestamp: datetime
    signature: str
    transaction_id: Optional[str] = None
    refund_amount: Optional[Decimal] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_data: Optional[Dict[str, Any]] = None

@dataclass
class PaymentCheckResponse:
    """Результат проверки платежа."""
    payment_id: str
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    order_id: str
    is_final: bool
    can_retry: bool
    last_checked: datetime = field(default_factory=datetime.utcnow)
    next_check_after: Optional[datetime] = None
    transaction_id: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

class PaymentError(Exception):
    """Базовое исключение для ошибок платежей."""
    pass

class PaymentTimeoutError(PaymentError):
    """Таймаут при выполнении платежной операции."""
    pass

class PaymentNetworkError(PaymentError):
    """Ошибка сети при выполнении запроса."""
    pass

class PaymentValidationError(PaymentError):
    """Ошибка валидации данных."""
    pass

class PaymentSecurityError(PaymentError):
    """Ошибка безопасности (неверная подпись и т.д.)."""
    pass

class PaymentGatewayError(PaymentError):
    """Ошибка платежного шлюза."""
    def __init__(self, message: str, code: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

class PaymentRetryPolicy:
    """Политика повторных попыток для платежных запросов."""
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        retry_on_statuses: List[int] = None,
        retry_on_exceptions: List[type] = None
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.retry_on_statuses = retry_on_statuses or [408, 429, 500, 502, 503, 504]
        self.retry_on_exceptions = retry_on_exceptions or [
            PaymentTimeoutError,
            PaymentNetworkError,
            asyncio.TimeoutError,
            aiohttp.ClientError,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ]
    
    def should_retry(
        self,
        attempt: int,
        status_code: Optional[int] = None,
        exception: Optional[Exception] = None
    ) -> bool:
        """Определяет, нужно ли повторять запрос."""
        if attempt >= self.max_retries:
            return False
        
        if status_code in self.retry_on_statuses:
            return True
        
        if exception:
            for retry_exception in self.retry_on_exceptions:
                if isinstance(exception, retry_exception):
                    return True
        
        return False
    
    def get_delay(self, attempt: int) -> float:
        """Расчет задержки перед повторной попыткой."""
        delay = self.initial_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)

class PaymentGatewayClient:
    """Клиент для работы с платежным API с таймаутами и обработкой ответов."""
    
    def __init__(
        self,
        api_url: str,
        api_key: str,
        secret_key: str,
        merchant_id: str,
        timeout_config: Optional[Dict[str, float]] = None,
        retry_policy: Optional[PaymentRetryPolicy] = None,
        enable_async: bool = True,
        verify_ssl: bool = True,
        proxy_url: Optional[str] = None
    ):
        """
        Инициализация клиента платежного шлюза.
        
        Args:
            api_url: URL платежного API
            api_key: Публичный ключ API
            secret_key: Секретный ключ для подписи
            merchant_id: Идентификатор мерчанта
            timeout_config: Конфигурация таймаутов
            retry_policy: Политика повторных попыток
            enable_async: Включить асинхронный режим
            verify_ssl: Проверять SSL сертификаты
            proxy_url: URL прокси-сервера
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.secret_key = secret_key.encode('utf-8')
        self.merchant_id = merchant_id
        self.enable_async = enable_async
        
        # Конфигурация таймаутов
        self.timeout_config = timeout_config or {
            'connect': 10.0,
            'read': 30.0,
            'write': 30.0,
            'total': 60.0,
            'webhook_process': 5.0
        }
        
        # Политика повторных попыток
        self.retry_policy = retry_policy or PaymentRetryPolicy()
        
        # Конфигурация сессии
        self.ssl_context = None
        if verify_ssl:
            self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        self.proxy_url = proxy_url
        
        # Инициализация сессий
        self._sync_session = None
        self._async_session = None
        
        # Статистика запросов
        self._request_stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'timeouts': 0,
            'retries': 0
        }
    
    @property
    def sync_session(self) -> requests.Session:
        """Получение синхронной HTTP сессии."""
        if self._sync_session is None:
            self._sync_session = self._create_sync_session()
        return self._sync_session
    
    def _create_sync_session(self) -> requests.Session:
        """Создание синхронной HTTP сессии."""
        session = requests.Session()
        session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': f'PaymentGatewayClient/{self.merchant_id}',
            'Authorization': f'Bearer {self.api_key}'
        })
        
        if self.proxy_url:
            session.proxies.update({'http': self.proxy_url, 'https': self.proxy_url})
        
        return session
    
    @property
    def async_session(self) -> aiohttp.ClientSession:
        """Получение асинхронной HTTP сессии."""
        if self._async_session is None and self.enable_async:
            self._async_session = self._create_async_session()
        return self._async_session
    
    def _create_async_session(self) -> aiohttp.ClientSession:
        """Создание асинхронной HTTP сессии."""
        timeout = aiohttp.ClientTimeout(
            total=self.timeout_config.get('total', 60.0),
            connect=self.timeout_config.get('connect', 10.0),
            sock_read=self.timeout_config.get('read', 30.0),
            sock_connect=self.timeout_config.get('connect', 10.0)
        )
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': f'PaymentGatewayClient/{self.merchant_id}',
            'Authorization': f'Bearer {self.api_key}'
        }
        
        return aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=aiohttp.TCPConnector(ssl=self.ssl_context)
        )
    
    def _generate_signature(self, data: Dict[str, Any], timestamp: str) -> str:
        """Генерация HMAC-SHA512 подписи."""
        # Сортировка ключей для консистентности
        sorted_data = json.dumps(data, sort_keys=True, separators=(',', ':'))
        
        # Создание строки для подписи
        message = f"{timestamp}.{sorted_data}.{self.merchant_id}"
        
        # Генерация HMAC-SHA512
        signature = hmac.new(
            self.secret_key,
            message.encode('utf-8'),
            hashlib.sha512
        )
        
        return signature.hexdigest()
    
    def _verify_signature(self, data: Dict[str, Any], signature: str, timestamp: str) -> bool:
        """Проверка HMAC-SHA512 подписи."""
        expected_signature = self._generate_signature(data, timestamp)
        return hmac.compare_digest(signature, expected_signature)
    
    def _prepare_request_data(self, endpoint: str, data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """Подготовка данных и заголовков для запроса."""
        timestamp = str(int(time.time()))
        
        # Добавление служебных полей
        request_data = {
            'merchant_id': self.merchant_id,
            'timestamp': timestamp,
            'nonce': hashlib.md5(f"{timestamp}{endpoint}".encode()).hexdigest()[:16],
            'version': '1.0',
            **data
        }
        
        # Генерация подписи
        signature = self._generate_signature(request_data, timestamp)
        
        # Заголовки
        headers = {
            'X-Merchant-ID': self.merchant_id,
            'X-Timestamp': timestamp,
            'X-Signature': signature,
            'X-Nonce': request_data['nonce']
        }
        
        return request_data, headers
    
    def _handle_response(
        self,
        response_data: Dict[str, Any],
        endpoint: str
    ) -> Dict[str, Any]:
        """Обработка ответа от платежного API."""
        # Проверка обязательных полей
        required_fields = ['status', 'code', 'message']
        for field in required_fields:
            if field not in response_data:
                raise PaymentGatewayError(
                    f"Missing required field '{field}' in response",
                    code="INVALID_RESPONSE",
                    details={'endpoint': endpoint}
                )
        
        # Проверка статуса ответа
        if response_data['status'] != 'success':
            error_code = response_data.get('error_code', response_data['code'])
            error_message = response_data.get('error_message', response_data['message'])
            
            # Классификация ошибок
            if response_data['code'] in ['TIMEOUT', 'GATEWAY_TIMEOUT']:
                raise PaymentTimeoutError(f"Payment gateway timeout: {error_message}")
            elif response_data['code'] in ['VALIDATION_ERROR', 'INVALID_REQUEST']:
                raise PaymentValidationError(f"Validation error: {error_message}")
            elif response_data['code'] in ['SECURITY_ERROR', 'INVALID_SIGNATURE']:
                raise PaymentSecurityError(f"Security error: {error_message}")
            else:
                raise PaymentGatewayError(
                    f"Payment gateway error: {error_message}",
                    code=error_code,
                    details=response_data.get('details', {})
                )
        
        # Проверка подписи ответа
        if 'signature' in response_data and 'timestamp' in response_data:
            signature = response_data.pop('signature')
            timestamp = response_data['timestamp']
            
            if not self._verify_signature(response_data, signature, timestamp):
                raise PaymentSecurityError("Invalid response signature")
            
            response_data['signature'] = signature
        
        return response_data['data'] if 'data' in response_data else response_data
    
    def _make_sync_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Выполнение синхронного HTTP запроса."""
        url = urljoin(self.api_url + '/', endpoint)
        
        # Подготовка данных и заголовков
        request_data, headers = self._prepare_request_data(endpoint, data or {})
        
        # Подготовка параметров запроса
        request_kwargs = {
            'headers': {**self.sync_session.headers, **headers},
            'timeout': (
                self.timeout_config.get('connect', 10.0),
                self.timeout_config.get('read', 30.0)
            )
        }
        
        if method.upper() == 'GET':
            if params:
                request_kwargs['params'] = params
        else:
            request_kwargs['json'] = request_data
        
        attempt = 0
        last_exception = None
        
        while True:
            attempt += 1
            self._request_stats['total'] += 1
            
            try:
                response = self.sync_session.request(
                    method,
                    url,
                    **request_kwargs
                )
                
                # Обработка HTTP ошибок
                if response.status_code >= 500:
                    raise PaymentNetworkError(f"Server error: {response.status_code}")
                elif response.status_code >= 400:
                    # Не повторяем для клиентских ошибок
                    if response.status_code == 408:  # Request Timeout
                        raise PaymentTimeoutError("Request timeout")
                    else:
                        error_data = response.json() if response.content else {}
                        raise PaymentGatewayError(
                            f"Client error: {response.status_code}",
                            code=f"HTTP_{response.status_code}",
                            details=error_data
                        )
                
                # Парсинг ответа
                response_data = response.json()
                
                # Обработка ответа
                processed_data = self._handle_response(response_data, endpoint)
                
                self._request_stats['success'] += 1
                return processed_data
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectTimeout) as e:
                last_exception = PaymentTimeoutError(f"Connection timeout: {str(e)}")
                self._request_stats['timeouts'] += 1
                logger.warning(f"Timeout on attempt {attempt} for {endpoint}")
                
            except requests.exceptions.ConnectionError as e:
                last_exception = PaymentNetworkError(f"Connection error: {str(e)}")
                self._request_stats['failed'] += 1
                logger.error(f"Connection error on attempt {attempt} for {endpoint}")
                
            except requests.exceptions.RequestException as e:
                last_exception = PaymentNetworkError(f"Network error: {str(e)}")
                self._request_stats['failed'] += 1
                logger.error(f"Network error on attempt {attempt} for {endpoint}")
                
            except PaymentGatewayError:
                raise  # Пропускаем ошибки шлюза
                
            except Exception as e:
                last_exception = PaymentError(f"Unexpected error: {str(e)}")
                self._request_stats['failed'] += 1
                logger.exception(f"Unexpected error on attempt {attempt} for {endpoint}")
            
            # Проверка необходимости повторной попытки
            if not self.retry_policy.should_retry(attempt, None, last_exception):
                break
            
            # Задержка перед повторной попыткой
            delay = self.retry_policy.get_delay(attempt - 1)
            self._request_stats['retries'] += 1
            time.sleep(delay)
        
        # Если дошли сюда, все попытки исчерпаны
        raise last_exception or PaymentError("All retry attempts failed")
    
    async def _make_async_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Выполнение асинхронного HTTP запроса."""
        if not self.enable_async:
            raise PaymentError("Async mode is not enabled")
        
        url = urljoin(self.api_url + '/', endpoint)
        
        # Подготовка данных и заголовков
        request_data, headers = self._prepare_request_data(endpoint, data or {})
        
        attempt = 0
        last_exception = None
        
        while True:
            attempt += 1
            self._request_stats['total'] += 1
            
            try:
                async with self.async_session.request(
                    method,
                    url,
                    json=request_data if method.upper() != 'GET' else None,
                    params=params if method.upper() == 'GET' else None,
                    headers=headers
                ) as response:
                    
                    # Обработка HTTP ошибок
                    if response.status >= 500:
                        raise PaymentNetworkError(f"Server error: {response.status}")
                    elif response.status >= 400:
                        # Не повторяем для клиентских ошибок
                        if response.status == 408:  # Request Timeout
                            raise PaymentTimeoutError("Request timeout")
                        else:
                            error_data = await response.json() if response.content else {}
                            raise PaymentGatewayError(
                                f"Client error: {response.status}",
                                code=f"HTTP_{response.status}",
                                details=error_data
                            )
                    
                    # Парсинг ответа
                    response_data = await response.json()
                    
                    # Обработка ответа
                    processed_data = self._handle_response(response_data, endpoint)
                    
                    self._request_stats['success'] += 1
                    return processed_data
                    
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as e:
                last_exception = PaymentTimeoutError(f"Connection timeout: {str(e)}")
                self._request_stats['timeouts'] += 1
                logger.warning(f"Timeout on async attempt {attempt} for {endpoint}")
                
            except aiohttp.ClientError as e:
                last_exception = PaymentNetworkError(f"Connection error: {str(e)}")
                self._request_stats['failed'] += 1
                logger.error(f"Connection error on async attempt {attempt} for {endpoint}")
                
            except PaymentGatewayError:
                raise  # Пропускаем ошибки шлюза
                
            except Exception as e:
                last_exception = PaymentError(f"Unexpected error: {str(e)}")
                self._request_stats['failed'] += 1
                logger.exception(f"Unexpected error on async attempt {attempt} for {endpoint}")
            
            # Проверка необходимости повторной попытки
            if not self.retry_policy.should_retry(attempt, None, last_exception):
                break
            
            # Задержка перед повторной попыткой
            delay = self.retry_policy.get_delay(attempt - 1)
            self._request_stats['retries'] += 1
            await asyncio.sleep(delay)
        
        # Если дошли сюда, все попытки исчерпаны
        raise last_exception or PaymentError("All retry attempts failed")
    
    def create_payment(self, payment_request: PaymentRequest) -> PaymentResponse:
        """
        Создание нового платежа.
        
        Args:
            payment_request: Данные платежного запроса
            
        Returns:
            Ответ с данными платежа
        """
        endpoint = "api/v1/payments/create"
        
        # Подготовка данных
        data = {
            'amount': str(payment_request.amount),
            'currency': payment_request.currency.value,
            'order_id': payment_request.order_id,
            'description': payment_request.description,
            'customer': {
                'email': payment_request.customer_email,
                'ip': payment_request.customer_ip
            },
            'return_url': payment_request.return_url,
            'cancel_url': payment_request.cancel_url,
            'callback_url': payment_request.callback_url,
            'payment_method': payment_request.payment_method.value,
            'metadata': payment_request.metadata,
            'custom_fields': payment_request.custom_fields,
            'items': payment_request.items,
            'language': payment_request.language
        }
        
        # Выполнение запроса
        response_data = self._make_sync_request('POST', endpoint, data)
        
        # Создание объекта ответа
        return PaymentResponse(
            payment_id=response_data['payment_id'],
            status=PaymentStatus(response_data['status']),
            amount=Decimal(response_data['amount']),
            currency=Currency(response_data['currency']),
            order_id=response_data['order_id'],
            payment_url=response_data.get('payment_url'),
            qr_code_url=response_data.get('qr_code_url'),
            expires_at=datetime.fromisoformat(response_data['expires_at']) if 'expires_at' in response_data else None,
            transaction_id=response_data.get('transaction_id'),
            error_code=response_data.get('error_code'),
            error_message=response_data.get('error_message'),
            raw_response=response_data
        )
    
    async def create_payment_async(self, payment_request: PaymentRequest) -> PaymentResponse:
        """Асинхронное создание платежа."""
        endpoint = "api/v1/payments/create"
        
        # Подготовка данных
        data = {
            'amount': str(payment_request.amount),
            'currency': payment_request.currency.value,
            'order_id': payment_request.order_id,
            'description': payment_request.description,
            'customer': {
                'email': payment_request.customer_email,
                'ip': payment_request.customer_ip
            },
            'return_url': payment_request.return_url,
            'cancel_url': payment_request.cancel_url,
            'callback_url': payment_request.callback_url,
            'payment_method': payment_request.payment_method.value,
            'metadata': payment_request.metadata,
            'custom_fields': payment_request.custom_fields,
            'items': payment_request.items,
            'language': payment_request.language
        }
        
        # Выполнение запроса
        response_data = await self._make_async_request('POST', endpoint, data)
        
        # Создание объекта ответа
        return PaymentResponse(
            payment_id=response_data['payment_id'],
            status=PaymentStatus(response_data['status']),
            amount=Decimal(response_data['amount']),
            currency=Currency(response_data['currency']),
            order_id=response_data['order_id'],
            payment_url=response_data.get('payment_url'),
            qr_code_url=response_data.get('qr_code_url'),
            expires_at=datetime.fromisoformat(response_data['expires_at']) if 'expires_at' in response_data else None,
            transaction_id=response_data.get('transaction_id'),
            error_code=response_data.get('error_code'),
            error_message=response_data.get('error_message'),
            raw_response=response_data
        )
    
    def get_payment_status(self, payment_id: str) -> PaymentCheckResponse:
        """
        Проверка статуса платежа.
        
        Args:
            payment_id: Идентификатор платежа
            
        Returns:
            Статус платежа
        """
        endpoint = f"api/v1/payments/{payment_id}/status"
        
        # Выполнение запроса
        response_data = self._make_sync_request('GET', endpoint)
        
        # Определение, является ли статус финальным
        status = PaymentStatus(response_data['status'])
        is_final = status in [
            PaymentStatus.SUCCESS,
            PaymentStatus.FAILED,
            PaymentStatus.DECLINED,
            PaymentStatus.CANCELLED,
            PaymentStatus.EXPIRED
        ]
        
        # Определение возможности повторной попытки
        can_retry = status in [
            PaymentStatus.FAILED,
            PaymentStatus.DECLINED
        ]
        
        # Расчет следующей проверки
        next_check_after = None
        if not is_final:
            next_check_after = datetime.utcnow() + timedelta(seconds=30)
        
        return PaymentCheckResponse(
            payment_id=response_data['payment_id'],
            status=status,
            amount=Decimal(response_data['amount']),
            currency=Currency(response_data['currency']),
            order_id=response_data['order_id'],
            is_final=is_final,
            can_retry=can_retry,
            next_check_after=next_check_after,
            transaction_id=response_data.get('transaction_id'),
            error_details=response_data.get('error_details')
        )
    
    def refund_payment(
        self,
        payment_id: str,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Возврат средств по платежу.
        
        Args:
            payment_id: Идентификатор платежа
            amount: Сумма возврата (если None - полный возврат)
            reason: Причина возврата
            
        Returns:
            Данные возврата
        """
        endpoint = f"api/v1/payments/{payment_id}/refund"
        
        data = {}
        if amount is not None:
            data['amount'] = str(amount)
        if reason:
            data['reason'] = reason
        
        return self._make_sync_request('POST', endpoint, data)
    
    def process_webhook(
        self,
        raw_data: Dict[str, Any],
        signature: str,
        timestamp: str
    ) -> PaymentWebhook:
        """
        Обработка вебхука от платежной системы.
        
        Args:
            raw_data: Сырые данные вебхука
            signature: Подпись вебхука
            timestamp: Временная метка
            
        Returns:
            Валидированный вебхук
        """
        # Проверка подписи
        if not self._verify_signature(raw_data, signature, timestamp):
            raise PaymentSecurityError("Invalid webhook signature")
        
        # Валидация обязательных полей
        required_fields = ['payment_id', 'status', 'amount', 'currency', 'order_id']
        for field in required_fields:
            if field not in raw_data:
                raise PaymentValidationError(f"Missing required field '{field}' in webhook")
        
        return PaymentWebhook(
            payment_id=raw_data['payment_id'],
            status=PaymentStatus(raw_data['status']),
            amount=Decimal(raw_data['amount']),
            currency=Currency(raw_data['currency']),
            order_id=raw_data['order_id'],
            timestamp=datetime.fromisoformat(raw_data.get('timestamp', datetime.utcnow().isoformat())),
            signature=signature,
            transaction_id=raw_data.get('transaction_id'),
            refund_amount=Decimal(raw_data['refund_amount']) if 'refund_amount' in raw_data else None,
            metadata=raw_data.get('metadata', {}),
            raw_data=raw_data
        )
    
    def batch_payments_status(self, payment_ids: List[str]) -> List[PaymentCheckResponse]:
        """
        Массовая проверка статусов платежей.
        
        Args:
            payment_ids: Список идентификаторов платежей
            
        Returns:
            Список статусов платежей
        """
        endpoint = "api/v1/payments/batch-status"
        
        data = {'payment_ids': payment_ids}
        response_data = self._make_sync_request('POST', endpoint, data)
        
        results = []
        for payment_data in response_data['payments']:
            status = PaymentStatus(payment_data['status'])
            is_final = status in [
                PaymentStatus.SUCCESS,
                PaymentStatus.FAILED,
                PaymentStatus.DECLINED,
                PaymentStatus.CANCELLED,
                PaymentStatus.EXPIRED
            ]
            
            results.append(PaymentCheckResponse(
                payment_id=payment_data['payment_id'],
                status=status,
                amount=Decimal(payment_data['amount']),
                currency=Currency(payment_data['currency']),
                order_id=payment_data['order_id'],
                is_final=is_final,
                can_retry=status in [PaymentStatus.FAILED, PaymentStatus.DECLINED],
                transaction_id=payment_data.get('transaction_id'),
                error_details=payment_data.get('error_details')
            ))
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики запросов."""
        return {
            **self._request_stats,
            'success_rate': (
                (self._request_stats['success'] / self._request_stats['total'] * 100)
                if self._request_stats['total'] > 0 else 0
            ),
            'timestamp': datetime.utcnow().isoformat()
        }
    
    def close(self):
        """Закрытие сессий и освобождение ресурсов."""
        if self._sync_session:
            self._sync_session.close()
            self._sync_session = None
        
        if self._async_session and not self._async_session.closed:
            if self.enable_async:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # В запущенном event loop'е закрываем асинхронно
                        asyncio.create_task(self._async_session.close())
                    else:
                        # Иначе закрываем синхронно
                        loop.run_until_complete(self._async_session.close())
                except:
                    pass
            self._async_session = None
    
    def __enter__(self):
        """Поддержка контекстного менеджера."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Закрытие сессий при выходе из контекста."""
        self.close()
    
    async def __aenter__(self):
        """Асинхронная поддержка контекстного менеджера."""
        if self.enable_async and self._async_session is None:
            self._async_session = self._create_async_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронное закрытие сессий."""
        if self._async_session and not self._async_session.closed:
            await self._async_session.close()
            self._async_session = None
        if self._sync_session:
            self._sync_session.close()
            self._sync_session = None