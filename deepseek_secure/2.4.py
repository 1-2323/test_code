import json
import logging
from typing import Any, Dict, Optional, Union
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import ssl

logger = logging.getLogger(__name__)


class TLSAdapter(HTTPAdapter):
    """Кастомный адаптер для контроля параметров TLS"""
    
    def __init__(self, ssl_version=ssl.PROTOCOL_TLS_CLIENT, **kwargs):
        self.ssl_version = ssl_version
        super().__init__(**kwargs)
    
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.minimum_version = self.ssl_version
        
        # Настройка предпочтительных шифров
        ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20')
        
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


class APIClient:
    """Клиент для безопасного взаимодействия с внешним API"""
    
    def __init__(
        self,
        base_url: str,
        api_key: str,
        ca_cert_path: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Инициализация клиента API.
        
        Args:
            base_url: Базовый URL API
            api_key: Ключ API для авторизации
            ca_cert_path: Путь к кастомному CA bundle (опционально)
            timeout: Таймаут запроса в секундах
            max_retries: Максимальное количество повторных попыток
        """
        if not base_url:
            raise ValueError("Base URL cannot be empty")
        
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.session = self._create_session(ca_cert_path, max_retries)
        
        logger.info(f"API клиент инициализирован для {self.base_url}")
    
    def _create_session(self, ca_cert_path: Optional[str], max_retries: int) -> requests.Session:
        """Создание сессии с правильной настройкой безопасности"""
        session = requests.Session()
        
        # Настройка заголовков по умолчанию
        session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        # Настройка адаптера с современными параметрами TLS
        adapter = TLSAdapter(ssl_version=ssl.PROTOCOL_TLS_CLIENT)
        session.mount('https://', adapter)
        
        # Настройка повторных попыток
        retry_adapter = HTTPAdapter(max_retries=max_retries)
        session.mount('http://', retry_adapter)
        
        # Настройка проверки сертификатов
        if ca_cert_path:
            session.verify = ca_cert_path
            logger.debug(f"Используется кастомный CA bundle: {ca_cert_path}")
        else:
            session.verify = True  # Использует системные корневые сертификаты
            
        return session
    
    def _build_url(self, endpoint: str) -> str:
        """Построение полного URL"""
        if not endpoint.startswith('/'):
            endpoint = '/' + endpoint
        return f"{self.base_url}{endpoint}"
    
    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Обработка ответа от сервера"""
        try:
            response.raise_for_status()
            
            # Пустой ответ для статусов No Content
            if response.status_code == 204:
                return {}
                
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP ошибка {response.status_code}: {response.text}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка декодирования JSON: {e}")
            raise ValueError(f"Invalid JSON response: {response.text}")
    
    def request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Выполнение HTTP запроса.
        
        Args:
            method: HTTP метод (GET, POST, PUT, DELETE, etc.)
            endpoint: Конечная точка API
            data: Тело запроса (для POST/PUT)
            params: Query параметры
            headers: Дополнительные заголовки
            
        Returns:
            Ответ API в виде словаря
            
        Raises:
            requests.exceptions.RequestException: При ошибках сети
            ValueError: При некорректном ответе
        """
        url = self._build_url(endpoint)
        request_headers = self.session.headers.copy()
        
        if headers:
            request_headers.update(headers)
        
        logger.debug(f"Отправка {method} запроса на {url}")
        
        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                json=data,
                params=params,
                headers=request_headers,
                timeout=self.timeout
            )
            
            return self._handle_response(response)
            
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL ошибка: {e}")
            raise ConnectionError(f"SSL verification failed: {e}")
        except requests.exceptions.Timeout as e:
            logger.error(f"Таймаут запроса: {e}")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ошибка соединения: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса: {e}")
            raise
    
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """GET запрос"""
        return self.request('GET', endpoint, params=params, **kwargs)
    
    def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """POST запрос"""
        return self.request('POST', endpoint, data=data, **kwargs)
    
    def put(self, endpoint: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """PUT запрос"""
        return self.request('PUT', endpoint, data=data, **kwargs)
    
    def delete(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """DELETE запрос"""
        return self.request('DELETE', endpoint, **kwargs)
    
    def close(self):
        """Закрытие сессии"""
        if self.session:
            self.session.close()
            logger.info("Сессия API клиента закрыта")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Пример конфигурации для использования
if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Конфигурация клиента
    CONFIG = {
        'base_url': 'https://api.example.com/v1',
        'api_key': 'your-secret-api-key-here',
        'ca_cert_path': None,  # Использует системные сертификаты
        'timeout': 30,
        'max_retries': 3
    }
    
    # Создание и использование клиента (пример)
    try:
        client = APIClient(**CONFIG)
        
        # GET запрос с параметрами
        # response = client.get('/users', params={'page': 1, 'limit': 10})
        
        # POST запрос с данными
        # data = {'name': 'John Doe', 'email': 'john@example.com'}
        # response = client.post('/users', data=data)
        
        logger.info("API клиент готов к использованию")
        
    except Exception as e:
        logger.error(f"Ошибка инициализации клиента: {e}")