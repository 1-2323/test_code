"""
Клиент для интеграции с внешними API через HTTPS
с поддержкой авторизации, обработки JSON и логирования.
"""

import json
import logging
import ssl
from datetime import datetime
from typing import Dict, Any, Optional, Union, Tuple
from urllib.parse import urljoin
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


class ApiLogger:
    """Кастомный логгер для API запросов."""
    
    def __init__(self, name: str = "ExternalApiClient", log_file: Optional[str] = None):
        """
        Инициализация логгера.
        
        Args:
            name: Имя логгера
            log_file: Путь к файлу логов (если None - только консоль)
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Форматтер для логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Обработчик для консоли
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Обработчик для файла (если указан)
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
    
    def log_request(self, 
                    method: str, 
                    url: str, 
                    headers: Optional[Dict] = None,
                    data: Optional[Any] = None):
        """Логирует информацию о запросе."""
        log_data = {
            'method': method,
            'url': url,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if headers:
            # Не логируем чувствительные заголовки полностью
            safe_headers = headers.copy()
            if 'Authorization' in safe_headers:
                safe_headers['Authorization'] = 'Bearer ***'
            
            log_data['headers'] = safe_headers
        
        self.logger.info(f"Запрос: {json.dumps(log_data, ensure_ascii=False)}")
        
        if data and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"Тело запроса: {data}")
    
    def log_response(self, 
                     method: str, 
                     url: str, 
                     status_code: int,
                     response_time: float,
                     response_data: Optional[Any] = None):
        """Логирует информацию об ответе."""
        log_entry = {
            'method': method,
            'url': url,
            'status_code': status_code,
            'response_time_ms': round(response_time * 1000, 2),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        level = logging.INFO if status_code < 400 else logging.ERROR
        self.logger.log(level, f"Ответ: {json.dumps(log_entry, ensure_ascii=False)}")
        
        if response_data and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"Тело ответа: {response_data}")
    
    def log_error(self, 
                  method: str, 
                  url: str, 
                  error: Exception,
                  context: Optional[Dict] = None):
        """Логирует ошибки."""
        error_data = {
            'method': method,
            'url': url,
            'error_type': type(error).__name__,
            'error_message': str(error),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if context:
            error_data.update(context)
        
        self.logger.error(f"Ошибка: {json.dumps(error_data, ensure_ascii=False)}")


class RetryStrategy:
    """Стратегия повторных попыток для API запросов."""
    
    def __init__(self, 
                 total_retries: int = 3,
                 backoff_factor: float = 0.5,
                 status_forcelist: Tuple[int, ...] = (500, 502, 503, 504)):
        """
        Инициализация стратегии повторных попыток.
        
        Args:
            total_retries: Общее количество повторных попыток
            backoff_factor: Фактор экспоненциальной задержки
            status_forcelist: Коды статусов для повторных попыток
        """
        self.total_retries = total_retries
        self.backoff_factor = backoff_factor
        self.status_forcelist = status_forcelist
    
    def create_adapter(self) -> HTTPAdapter:
        """
        Создает HTTP адаптер с настроенной стратегией повторных попыток.
        
        Returns:
            Настроенный HTTPAdapter
        """
        retry_strategy = Retry(
            total=self.total_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=list(self.status_forcelist),
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        return adapter


class ExternalApiClient:
    """Клиент для работы с внешними API."""
    
    def __init__(self, 
                 base_url: str,
                 api_token: Optional[str] = None,
                 timeout: int = 30,
                 verify_ssl: bool = True,
                 enable_logging: bool = True):
        """
        Инициализация API клиента.
        
        Args:
            base_url: Базовый URL API
            api_token: Токен авторизации (если требуется)
            timeout: Таймаут запросов в секундах
            verify_ssl: Проверять ли SSL сертификаты
            enable_logging: Включить ли логирование
        """
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        
        # Настройка сессии requests
        self.session = requests.Session()
        
        # Настройка стратегии повторных попыток
        retry_strategy = RetryStrategy()
        adapter = retry_strategy.create_adapter()
        
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Настройка SSL (если нужно отключить проверку)
        if not verify_ssl:
            self.session.verify = False
            requests.packages.urllib3.disable_warnings()
        
        # Настройка заголовков по умолчанию
        self.session.headers.update({
            'User-Agent': 'ExternalApiClient/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        
        if api_token:
            self.session.headers.update({
                'Authorization': f'Bearer {api_token}'
            })
        
        # Настройка логирования
        self.enable_logging = enable_logging
        if enable_logging:
            self.logger = ApiLogger()
        else:
            self.logger = None
    
    def _build_url(self, endpoint: str) -> str:
        """
        Строит полный URL из базового и эндпоинта.
        
        Args:
            endpoint: Относительный путь эндпоинта
            
        Returns:
            Полный URL
        """
        return urljoin(f"{self.base_url}/", endpoint.lstrip('/'))
    
    def _prepare_data(self, data: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Подготавливает данные для отправки.
        
        Args:
            data: Данные для отправки
            
        Returns:
            JSON строка или None
        """
        if data is None:
            return None
        return json.dumps(data, ensure_ascii=False)
    
    def post(self, 
             endpoint: str, 
             data: Optional[Dict[str, Any]] = None,
             additional_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Отправляет POST запрос к API.
        
        Args:
            endpoint: Относительный путь эндпоинта
            data: Данные для отправки
            additional_headers: Дополнительные заголовки
            
        Returns:
            Ответ от API в виде словаря
            
        Raises:
            requests.exceptions.RequestException: При ошибке запроса
            ValueError: При некорректном ответе
        """
        url = self._build_url(endpoint)
        json_data = self._prepare_data(data)
        
        # Подготавливаем заголовки
        headers = self.session.headers.copy()
        if additional_headers:
            headers.update(additional_headers)
        
        # Логируем запрос
        if self.enable_logging and self.logger:
            self.logger.log_request('POST', url, headers, data)
        
        try:
            start_time = datetime.utcnow()
            
            # Отправляем запрос
            response = self.session.post(
                url=url,
                data=json_data,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            
            # Измеряем время выполнения
            response_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Логируем ответ
            if self.enable_logging and self.logger:
                self.logger.log_response(
                    'POST', 
                    url, 
                    response.status_code, 
                    response_time,
                    response.text[:500]  # Логируем только первые 500 символов
                )
            
            # Проверяем статус код
            response.raise_for_status()
            
            # Пытаемся распарсить JSON
            try:
                return response.json()
            except json.JSONDecodeError as e:
                raise ValueError(f"Некорректный JSON в ответе: {str(e)}")
            
        except requests.exceptions.RequestException as e:
            # Логируем ошибку
            if self.enable_logging and self.logger:
                self.logger.log_error('POST', url, e)
            
            # Пробрасываем исключение дальше
            raise
    
    def get(self, 
            endpoint: str, 
            params: Optional[Dict[str, Any]] = None,
            additional_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Отправляет GET запрос к API.
        
        Args:
            endpoint: Относительный путь эндпоинта
            params: Параметры запроса
            additional_headers: Дополнительные заголовки
        """
        url = self._build_url(endpoint)
        
        # Подготавливаем заголовки
        headers = self.session.headers.copy()
        if additional_headers:
            headers.update(additional_headers)
        
        # Логируем запрос
        if self.enable_logging and self.logger:
            self.logger.log_request('GET', url, headers)
        
        try:
            start_time = datetime.utcnow()
            
            response = self.session.get(
                url=url,
                params=params,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            
            response_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Логируем ответ
            if self.enable_logging and self.logger:
                self.logger.log_response(
                    'GET', 
                    url, 
                    response.status_code, 
                    response_time,
                    response.text[:500]
                )
            
            response.raise_for_status()
            
            try:
                return response.json()
            except json.JSONDecodeError as e:
                raise ValueError(f"Некорректный JSON в ответе: {str(e)}")
            
        except requests.exceptions.RequestException as e:
            if self.enable_logging and self.logger:
                self.logger.log_error('GET', url, e)
            raise
    
    def update_token(self, new_token: str):
        """
        Обновляет токен авторизации.
        
        Args:
            new_token: Новый токен
        """
        self.api_token = new_token
        self.session.headers.update({
            'Authorization': f'Bearer {new_token}'
        })
    
    def close(self):
        """Закрывает сессию requests."""
        self.session.close()


# Пример использования для платежного шлюза
class PaymentGatewayClient(ExternalApiClient):
    """Специализированный клиент для платежного шлюза."""
    
    def __init__(self, 
                 api_key: str,
                 merchant_id: str,
                 base_url: str = "https://api.paymentgateway.com/v1"):
        """
        Инициализация клиента платежного шлюза.
        
        Args:
            api_key: API ключ мерчанта
            merchant_id: ID мерчанта
            base_url: Базовый URL API платежного шлюза
        """
        super().__init__(base_url=base_url, api_token=api_key)
        self.merchant_id = merchant_id
        
        # Обновляем заголовки для платежного шлюза
        self.session.headers.update({
            'X-Merchant-ID': merchant_id
        })
    
    def create_payment(self, 
                       amount: float, 
                       currency: str, 
                       order_id: str,
                       customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создает новый платеж.
        
        Args:
            amount: Сумма платежа
            currency: Валюта (USD, EUR, etc.)
            order_id: ID заказа
            customer_data: Данные клиента
            
        Returns:
            Ответ от платежного шлюза
        """
        payment_data = {
            'amount': amount,
            'currency': currency.upper(),
            'order_id': order_id,
            'merchant_id': self.merchant_id,
            'customer': customer_data,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return self.post('/payments/create', data=payment_data)
    
    def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """
        Получает статус платежа.
        
        Args:
            payment_id: ID платежа
            
        Returns:
            Статус платежа
        """
        return self.get(f'/payments/{payment_id}/status')


# Пример использования
if __name__ == "__main__":
    # Инициализация клиента платежного шлюза
    payment_client = PaymentGatewayClient(
        api_key="your_api_key_here",
        merchant_id="your_merchant_id_here",
        base_url="https://sandbox.paymentgateway.com/v1"
    )
    
    try:
        # Создание платежа
        payment_data = {
            'amount': 99.99,
            'currency': 'USD',
            'order_id': 'ORDER-12345',
            'customer_data': {
                'email': 'customer@example.com',
                'name': 'John Doe'
            }
        }
        
        # Это пример - раскомментируйте для реального использования
        # response = payment_client.create_payment(**payment_data)
        # print(f"Ответ платежного шлюза: {response}")
        
        # Имитация ответа для примера
        mock_response = {
            "success": True,
            "payment_id": "pay_123456789",
            "status": "pending",
            "redirect_url": "https://paymentgateway.com/redirect/pay_123456789"
        }
        print(f"Мок ответ платежного шлюза: {mock_response}")
        
    except Exception as e:
        print(f"Ошибка при работе с платежным шлюзом: {e}")
    finally:
        # Всегда закрываем сессию
        payment_client.close()