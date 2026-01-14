import json
import hashlib
import hmac
import requests
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urljoin

class LicenseClient:
    """Клиент для проверки лицензий через внешний сервер."""
    
    def __init__(
        self,
        api_url: str,
        api_key: str,
        product_id: str,
        timeout: int = 10,
        verify_ssl: bool = True
    ):
        """
        Инициализация клиента лицензирования.
        
        Args:
            api_url: Базовый URL сервера лицензий
            api_key: Секретный ключ для подписи запросов
            product_id: Идентификатор продукта
            timeout: Таймаут запросов в секундах
            verify_ssl: Проверять SSL-сертификат
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key.encode('utf-8')
        self.product_id = product_id
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.client_id = self._get_client_id()
        
    def _get_client_id(self) -> str:
        """Генерирует уникальный идентификатор клиента."""
        try:
            import socket
            hostname = socket.gethostname()
            return hashlib.sha256(hostname.encode()).hexdigest()[:32]
        except:
            return str(uuid.uuid4())
    
    def _generate_signature(self, data: Dict[str, Any]) -> str:
        """
        Генерирует HMAC-SHA256 подпись для данных.
        
        Args:
            data: Данные для подписи
            
        Returns:
            HEX-строка с подписью
        """
        # Сортируем ключи для консистентности
        sorted_data = json.dumps(data, sort_keys=True, separators=(',', ':'))
        signature = hmac.new(
            self.api_key,
            sorted_data.encode('utf-8'),
            hashlib.sha256
        )
        return signature.hexdigest()
    
    def _make_request(
        self, 
        endpoint: str, 
        payload: Dict[str, Any]
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Выполняет запрос к серверу лицензий.
        
        Args:
            endpoint: Конечная точка API
            payload: Данные запроса
            
        Returns:
            Кортеж (успех, данные_ответа, сообщение_ошибки)
        """
        try:
            # Добавляем временную метку и подпись
            payload['timestamp'] = datetime.utcnow().isoformat()
            payload['signature'] = self._generate_signature(payload)
            
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': f'LicenseClient/{self.product_id}'
            }
            
            url = urljoin(self.api_url + '/', endpoint)
            
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            
            # Проверяем HTTP статус
            if response.status_code != 200:
                return False, None, f"HTTP ошибка: {response.status_code}"
            
            # Парсим ответ
            response_data = response.json()
            
            # Проверяем подпись ответа
            if not self._verify_response_signature(response_data):
                return False, None, "Неверная подпись ответа"
            
            return True, response_data, None
            
        except requests.exceptions.Timeout:
            return False, None, "Таймаут при соединении с сервером лицензий"
        except requests.exceptions.ConnectionError:
            return False, None, "Ошибка соединения с сервером лицензий"
        except requests.exceptions.RequestException as e:
            return False, None, f"Ошибка сети: {str(e)}"
        except json.JSONDecodeError:
            return False, None, "Некорректный JSON в ответе"
        except Exception as e:
            return False, None, f"Неизвестная ошибка: {str(e)}"
    
    def _verify_response_signature(self, response_data: Dict[str, Any]) -> bool:
        """
        Проверяет подпись ответа от сервера.
        
        Args:
            response_data: Данные ответа
            
        Returns:
            True если подпись верна
        """
        if 'signature' not in response_data:
            return False
        
        # Извлекаем подпись из ответа
        received_signature = response_data.pop('signature')
        
        # Генерируем подпись для оставшихся данных
        expected_signature = self._generate_signature(response_data)
        
        # Возвращаем подпись обратно в данные
        response_data['signature'] = received_signature
        
        # Сравниваем подписи безопасным способом
        return hmac.compare_digest(received_signature, expected_signature)
    
    def validate_license(
        self, 
        license_key: str,
        feature: Optional[str] = None,
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Проверяет валидность лицензии.
        
        Args:
            license_key: Ключ лицензии
            feature: Проверяемая функциональность (опционально)
            version: Версия продукта (опционально)
            
        Returns:
            Словарь с результатом проверки:
            {
                'valid': bool,
                'message': str,
                'data': Optional[Dict] - данные лицензии,
                'error_code': Optional[str] - код ошибки,
                'expires_at': Optional[str] - срок действия
            }
        """
        payload = {
            'license_key': license_key,
            'product_id': self.product_id,
            'client_id': self.client_id
        }
        
        if feature:
            payload['feature'] = feature
        if version:
            payload['version'] = version
        
        success, response_data, error_message = self._make_request(
            'api/v1/validate',
            payload
        )
        
        if not success:
            return {
                'valid': False,
                'message': error_message,
                'data': None,
                'error_code': 'NETWORK_ERROR',
                'expires_at': None
            }
        
        # Стандартизируем ответ
        if response_data.get('status') == 'valid':
            return {
                'valid': True,
                'message': response_data.get('message', 'Лицензия действительна'),
                'data': response_data.get('license_data', {}),
                'error_code': None,
                'expires_at': response_data.get('expires_at')
            }
        else:
            return {
                'valid': False,
                'message': response_data.get('message', 'Лицензия недействительна'),
                'data': None,
                'error_code': response_data.get('error_code', 'INVALID_LICENSE'),
                'expires_at': None
            }
    
    def activate_license(
        self, 
        license_key: str,
        user_data: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Активирует лицензию.
        
        Args:
            license_key: Ключ лицензии
            user_data: Данные пользователя (имя, email и т.д.)
            
        Returns:
            Словарь с результатом активации
        """
        payload = {
            'license_key': license_key,
            'product_id': self.product_id,
            'client_id': self.client_id
        }
        
        if user_data:
            payload['user_data'] = user_data
        
        success, response_data, error_message = self._make_request(
            'api/v1/activate',
            payload
        )
        
        if not success:
            return {
                'success': False,
                'message': error_message,
                'activation_id': None,
                'error_code': 'NETWORK_ERROR'
            }
        
        if response_data.get('status') == 'activated':
            return {
                'success': True,
                'message': response_data.get('message', 'Лицензия успешно активирована'),
                'activation_id': response_data.get('activation_id'),
                'error_code': None
            }
        else:
            return {
                'success': False,
                'message': response_data.get('message', 'Ошибка активации'),
                'activation_id': None,
                'error_code': response_data.get('error_code', 'ACTIVATION_FAILED')
            }
    
    def deactivate_license(self, license_key: str) -> Dict[str, Any]:
        """
        Деактивирует лицензию.
        
        Args:
            license_key: Ключ лицензии
            
        Returns:
            Словарь с результатом деактивации
        """
        payload = {
            'license_key': license_key,
            'product_id': self.product_id,
            'client_id': self.client_id
        }
        
        success, response_data, error_message = self._make_request(
            'api/v1/deactivate',
            payload
        )
        
        if not success:
            return {
                'success': False,
                'message': error_message,
                'error_code': 'NETWORK_ERROR'
            }
        
        if response_data.get('status') == 'deactivated':
            return {
                'success': True,
                'message': response_data.get('message', 'Лицензия успешно деактивирована'),
                'error_code': None
            }
        else:
            return {
                'success': False,
                'message': response_data.get('message', 'Ошибка деактивации'),
                'error_code': response_data.get('error_code', 'DEACTIVATION_FAILED')
            }
    
    def check_heartbeat(self) -> bool:
        """
        Проверяет доступность сервера лицензий.
        
        Returns:
            True если сервер доступен
        """
        try:
            response = requests.get(
                urljoin(self.api_url + '/', 'api/v1/health'),
                timeout=5,
                verify=self.verify_ssl
            )
            return response.status_code == 200
        except:
            return False