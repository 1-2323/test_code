import requests
import json
import logging
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass
import time

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LicenseStatus(Enum):
    """Статусы лицензии"""
    VALID = "VALID"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"
    SERVER_UNAVAILABLE = "SERVER_UNAVAILABLE"
    ERROR = "ERROR"


@dataclass
class LicenseResponse:
    """Структура ответа с сервера лицензирования"""
    status: LicenseStatus
    message: str
    data: Optional[dict] = None
    server_available: bool = True


class LicenseClient:
    """Клиент для проверки лицензии через внешний сервер"""
    
    def __init__(
        self,
        server_url: str,
        product_id: str,
        max_retries: int = 3,
        timeout: float = 10.0,
        fail_closed: bool = True
    ):
        """
        Инициализация клиента лицензирования
        
        Args:
            server_url: URL сервера лицензирования
            product_id: Идентификатор продукта
            max_retries: Максимальное количество попыток подключения
            timeout: Таймаут запроса в секундах
            fail_closed: Блокировать доступ при недоступности сервера
        """
        self.server_url = server_url.rstrip('/')
        self.product_id = product_id
        self.max_retries = max_retries
        self.timeout = timeout
        self.fail_closed = fail_closed
        self.license_endpoint = f"{self.server_url}/api/v1/license/validate"
        
    def validate_license(self, license_key: str, device_id: str) -> LicenseResponse:
        """
        Проверка лицензии через внешний сервер
        
        Args:
            license_key: Ключ лицензии
            device_id: Идентификатор устройства
            
        Returns:
            LicenseResponse: Результат проверки лицензии
        """
        for attempt in range(self.max_retries):
            try:
                response = self._make_license_request(license_key, device_id)
                
                if response.status == LicenseStatus.SERVER_UNAVAILABLE:
                    logger.warning(f"Сервер недоступен, попытка {attempt + 1}/{self.max_retries}")
                    if attempt < self.max_retries - 1:
                        time.sleep(2 ** attempt)  # Экспоненциальная задержка
                    continue
                    
                return response
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Ошибка сети при попытке {attempt + 1}: {str(e)}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                continue
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Ошибка обработки ответа: {str(e)}")
                return LicenseResponse(
                    status=LicenseStatus.ERROR,
                    message=f"Ошибка обработки ответа сервера: {str(e)}",
                    server_available=True
                )
        
        # Все попытки исчерпаны
        if self.fail_closed:
            logger.error("Сервер лицензирования недоступен, доступ заблокирован (fail-closed)")
            return LicenseResponse(
                status=LicenseStatus.SERVER_UNAVAILABLE,
                message="Сервер лицензирования недоступен. Доступ заблокирован.",
                server_available=False
            )
        else:
            logger.warning("Сервер лицензирования недоступен, доступ разрешен (fail-open)")
            return LicenseResponse(
                status=LicenseStatus.VALID,
                message="Сервер недоступен, доступ временно разрешен",
                server_available=False
            )
    
    def _make_license_request(self, license_key: str, device_id: str) -> LicenseResponse:
        """
        Выполнение запроса к серверу лицензирования
        
        Args:
            license_key: Ключ лицензии
            device_id: Идентификатор устройства
            
        Returns:
            LicenseResponse: Ответ сервера
        """
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': f'LicenseClient/{self.product_id}'
        }
        
        payload = {
            'product_id': self.product_id,
            'license_key': license_key,
            'device_id': device_id,
            'timestamp': int(time.time())
        }
        
        try:
            response = requests.post(
                self.license_endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            # Обработка HTTP ошибок
            if response.status_code == 503:
                return LicenseResponse(
                    status=LicenseStatus.SERVER_UNAVAILABLE,
                    message="Сервер лицензирования временно недоступен",
                    server_available=False
                )
            elif response.status_code != 200:
                return LicenseResponse(
                    status=LicenseStatus.ERROR,
                    message=f"Ошибка сервера: HTTP {response.status_code}",
                    server_available=True
                )
            
            # Парсинг ответа
            data = response.json()
            
            # Валидация структуры ответа
            if 'status' not in data or 'message' not in data:
                raise ValueError("Неверный формат ответа сервера")
            
            # Маппинг статуса из строки в Enum
            status_str = data.get('status', '').upper()
            try:
                status = LicenseStatus(status_str)
            except ValueError:
                status = LicenseStatus.ERROR
            
            return LicenseResponse(
                status=status,
                message=data.get('message', ''),
                data=data.get('data'),
                server_available=True
            )
            
        except requests.exceptions.Timeout:
            logger.error(f"Таймаут подключения к серверу лицензирования")
            return LicenseResponse(
                status=LicenseStatus.SERVER_UNAVAILABLE,
                message="Таймаут подключения к серверу лицензирования",
                server_available=False
            )
        except requests.exceptions.ConnectionError:
            logger.error(f"Ошибка подключения к серверу лицензирования")
            return LicenseResponse(
                status=LicenseStatus.SERVER_UNAVAILABLE,
                message="Не удалось подключиться к серверу лицензирования",
                server_available=False
            )


class LicenseManager:
    """Менеджер лицензий для управления доступом к функционалу"""
    
    def __init__(
        self,
        server_url: str,
        product_id: str,
        license_key: str,
        device_id: str,
        cache_ttl: int = 300,  # 5 минут
        fail_closed: bool = True
    ):
        """
        Инициализация менеджера лицензий
        
        Args:
            server_url: URL сервера лицензирования
            product_id: Идентификатор продукта
            license_key: Ключ лицензии
            device_id: Идентификатор устройства
            cache_ttl: Время жизни кэша в секундах
            fail_closed: Блокировать доступ при недоступности сервера
        """
        self.client = LicenseClient(
            server_url=server_url,
            product_id=product_id,
            fail_closed=fail_closed
        )
        self.license_key = license_key
        self.device_id = device_id
        self.cache_ttl = cache_ttl
        self._last_validation = None
        self._cached_response = None
        
    def check_access(self) -> Tuple[bool, str]:
        """
        Проверка доступа на основе лицензии
        
        Returns:
            Tuple[bool, str]: (Разрешен ли доступ, Сообщение)
        """
        # Проверка кэша
        current_time = time.time()
        if (self._cached_response and 
            self._last_validation and 
            (current_time - self._last_validation) < self.cache_ttl):
            logger.debug("Используется кэшированный результат проверки лицензии")
            return self._evaluate_response(self._cached_response)
        
        # Запрос к серверу
        response = self.client.validate_license(self.license_key, self.device_id)
        
        # Кэширование результата
        if response.server_available:
            self._cached_response = response
            self._last_validation = current_time
        
        return self._evaluate_response(response)
    
    def _evaluate_response(self, response: LicenseResponse) -> Tuple[bool, str]:
        """
        Оценка ответа от сервера лицензирования
        
        Args:
            response: Ответ от сервера
            
        Returns:
            Tuple[bool, str]: (Разрешен ли доступ, Сообщение)
        """
        if response.status in [LicenseStatus.VALID]:
            return True, response.message
            
        elif response.status == LicenseStatus.SERVER_UNAVAILABLE:
            if self.client.fail_closed:
                return False, f"Доступ заблокирован: {response.message}"
            else:
                logger.warning(f"Сервер недоступен, доступ временно разрешен: {response.message}")
                return True, response.message
                
        else:  # INVALID, EXPIRED, ERROR
            return False, f"Доступ запрещен: {response.message}"
    
    def force_validation(self) -> Tuple[bool, str]:
        """
        Принудительная проверка лицензии (игнорируя кэш)
        
        Returns:
            Tuple[bool, str]: (Разрешен ли доступ, Сообщение)
        """
        self._cached_response = None
        self._last_validation = None
        return self.check_access()