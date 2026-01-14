import json
import logging
from typing import Any, Dict, Optional, Union
from datetime import datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class APIClientError(Exception):
    """Базовое исключение для ошибок API клиента"""
    pass


class AuthenticationError(APIClientError):
    """Ошибка аутентификации"""
    pass


class RateLimitError(APIClientError):
    """Превышен лимит запросов"""
    pass


class ServiceUnavailableError(APIClientError):
    """Сервис недоступен"""
    pass


class SecureAPIClient:
    """
    Клиент для работы с защищенным внешним API через HTTPS
    с поддержкой авторизации через заголовки
    """
    
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        rate_limit_delay: int = 1
    ):
        """
        Инициализация клиента
        
        Args:
            base_url: Базовый URL API
            api_key: API ключ для авторизации (опционально)
            bearer_token: Bearer токен для авторизации (опционально)
            timeout: Таймаут запросов в секундах
            max_retries: Максимальное количество повторных попыток
            rate_limit_delay: Задержка при превышении лимита запросов в секундах
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self.session = self._create_session(max_retries)
        
        # Кэш для rate limiting
        self.last_request_time = None
        self.request_count = 0
        self.rate_limit_reset = None
        
        logger.info(f"Инициализирован клиент для API: {base_url}")
    
    def _create_session(self, max_retries: int) -> requests.Session:
        """
        Создание сессии с настройкой повторных попыток
        
        Args:
            max_retries: Максимальное количество повторных попыток
            
        Returns:
            Настроенная сессия requests
        """
        session = requests.Session()
        
        # Настройка стратегии повторных попыток
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        return session
    
    def _get_authorization_headers(self) -> Dict[str, str]:
        """
        Формирование заголовков авторизации
        
        Returns:
            Словарь с заголовками авторизации
            
        Raises:
            AuthenticationError: Если не предоставлены учетные данные
        """
        headers = {}
        
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        else:
            raise AuthenticationError(
                "Не предоставлены учетные данные для аутентификации. "
                "Укажите api_key или bearer_token."
            )
        
        return headers
    
    def _handle_rate_limiting(self):
        """
        Обработка rate limiting для соблюдения ограничений API
        """
        if self.last_request_time:
            current_time = datetime.now()
            time_since_last = (current_time - self.last_request_time).total_seconds()
            
            # Проверяем, не превысили ли мы лимит запросов
            if self.rate_limit_reset and current_time < self.rate_limit_reset:
                wait_time = (self.rate_limit_reset - current_time).total_seconds()
                logger.warning(f"Достигнут лимит запросов. Ожидание {wait_time:.2f} секунд")
                import time
                time.sleep(wait_time)
            
            # Добавляем задержку между запросами, если необходимо
            if time_since_last < self.rate_limit_delay:
                wait_time = self.rate_limit_delay - time_since_last
                import time
                time.sleep(wait_time)
        
        self.last_request_time = datetime.now()
    
    def _update_rate_limit_info(self, response: requests.Response):
        """
        Обновление информации о rate limiting из заголовков ответа
        
        Args:
            response: Ответ от API
        """
        if 'X-RateLimit-Remaining' in response.headers:
            remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
            if remaining == 0:
                reset_timestamp = int(response.headers.get('X-RateLimit-Reset', 0))
                if reset_timestamp > 0:
                    self.rate_limit_reset = datetime.fromtimestamp(reset_timestamp)
    
    def _handle_response_errors(self, response: requests.Response):
        """
        Обработка ошибок ответа
        
        Args:
            response: Ответ от API
            
        Raises:
            AuthenticationError: При ошибках аутентификации
            RateLimitError: При превышении лимита запросов
            ServiceUnavailableError: При недоступности сервиса
            APIClientError: При других ошибках API
        """
        status_code = response.status_code
        
        if status_code == 401:
            raise AuthenticationError(f"Ошибка аутентификации: {response.text}")
        elif status_code == 403:
            raise AuthenticationError(f"Доступ запрещен: {response.text}")
        elif status_code == 429:
            raise RateLimitError("Превышен лимит запросов к API")
        elif status_code >= 500:
            raise ServiceUnavailableError(
                f"Ошибка сервера ({status_code}): {response.text}"
            )
        elif status_code >= 400:
            raise APIClientError(
                f"Ошибка клиента ({status_code}): {response.text}"
            )
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """
        Выполнение HTTP запроса
        
        Args:
            method: HTTP метод (GET, POST, PUT, DELETE, etc.)
            endpoint: Конечная точка API
            params: Параметры запроса
            data: Данные для отправки
            json_data: JSON данные для отправки
            headers: Дополнительные заголовки
            
        Returns:
            Ответ от сервера
            
        Raises:
            APIClientError: При ошибках запроса
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Формируем заголовки
        request_headers = self._get_authorization_headers()
        if headers:
            request_headers.update(headers)
        
        if json_data is not None:
            request_headers.setdefault("Content-Type", "application/json")
        
        try:
            # Обрабатываем rate limiting
            self._handle_rate_limiting()
            
            logger.debug(f"Выполнение запроса {method} к {url}")
            
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=request_headers,
                timeout=self.timeout,
                verify=True  # Включаем проверку SSL сертификата
            )
            
            # Обновляем информацию о rate limiting
            self._update_rate_limit_info(response)
            
            # Обрабатываем ошибки
            if not response.ok:
                self._handle_response_errors(response)
            
            logger.debug(f"Получен ответ {response.status_code} от {url}")
            return response
            
        except requests.exceptions.Timeout:
            logger.error(f"Таймаут запроса к {url}")
            raise APIClientError(f"Таймаут запроса к {endpoint}")
        except requests.exceptions.ConnectionError:
            logger.error(f"Ошибка подключения к {url}")
            raise ServiceUnavailableError(f"Не удалось подключиться к {endpoint}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса к {url}: {str(e)}")
            raise APIClientError(f"Ошибка запроса: {str(e)}")
    
    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Выполнение GET запроса
        
        Args:
            endpoint: Конечная точка API
            params: Параметры запроса
            headers: Дополнительные заголовки
            
        Returns:
            Распарсенный JSON ответ
        """
        response = self._make_request(
            method="GET",
            endpoint=endpoint,
            params=params,
            headers=headers
        )
        return response.json()
    
    def post(
        self,
        endpoint: str,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Выполнение POST запроса
        
        Args:
            endpoint: Конечная точка API
            data: Данные для отправки
            json_data: JSON данные для отправки
            headers: Дополнительные заголовки
            
        Returns:
            Распарсенный JSON ответ
        """
        response = self._make_request(
            method="POST",
            endpoint=endpoint,
            data=data,
            json_data=json_data,
            headers=headers
        )
        return response.json()
    
    def put(
        self,
        endpoint: str,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Выполнение PUT запроса
        
        Args:
            endpoint: Конечная точка API
            data: Данные для отправки
            json_data: JSON данные для отправки
            headers: Дополнительные заголовки
            
        Returns:
            Распарсенный JSON ответ
        """
        response = self._make_request(
            method="PUT",
            endpoint=endpoint,
            data=data,
            json_data=json_data,
            headers=headers
        )
        return response.json()
    
    def delete(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Выполнение DELETE запроса
        
        Args:
            endpoint: Конечная точка API
            params: Параметры запроса
            headers: Дополнительные заголовки
            
        Returns:
            Распарсенный JSON ответ
        """
        response = self._make_request(
            method="DELETE",
            endpoint=endpoint,
            params=params,
            headers=headers
        )
        return response.json()
    
    def patch(
        self,
        endpoint: str,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Выполнение PATCH запроса
        
        Args:
            endpoint: Конечная точка API
            data: Данные для отправки
            json_data: JSON данные для отправки
            headers: Дополнительные заголовки
            
        Returns:
            Распарсенный JSON ответ
        """
        response = self._make_request(
            method="PATCH",
            endpoint=endpoint,
            data=data,
            json_data=json_data,
            headers=headers
        )
        return response.json()
    
    def download_file(
        self,
        endpoint: str,
        file_path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Загрузка файла из API
        
        Args:
            endpoint: Конечная точка API
            file_path: Путь для сохранения файла
            params: Параметры запроса
            headers: Дополнительные заголовки
            
        Returns:
            Путь к сохраненному файлу
        """
        response = self._make_request(
            method="GET",
            endpoint=endpoint,
            params=params,
            headers=headers
        )
        
        with open(file_path, 'wb') as file:
            file.write(response.content)
        
        logger.info(f"Файл сохранен: {file_path}")
        return file_path
    
    def set_bearer_token(self, token: str):
        """
        Установка bearer токена
        
        Args:
            token: Bearer токен
        """
        self.bearer_token = token
        logger.info("Bearer токен обновлен")
    
    def set_api_key(self, api_key: str):
        """
        Установка API ключа
        
        Args:
            api_key: API ключ
        """
        self.api_key = api_key
        logger.info("API ключ обновлен")
    
    def close(self):
        """Закрытие сессии"""
        if self.session:
            self.session.close()
            logger.info("Сессия закрыта")
    
    def __enter__(self):
        """Поддержка контекстного менеджера"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Закрытие сессии при выходе из контекста"""
        self.close()


if __name__ == "__main__":
    # Этот блок не будет выполняться при импорте,
    # только при прямом запуске файла
    print("SecureAPIClient инициализирован.")
    print("Для использования импортируйте класс и создайте экземпляр с вашими параметрами.")