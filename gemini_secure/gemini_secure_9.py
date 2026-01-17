import requests
import logging
import ipaddress
import socket
import json
import re
from typing import Any, Dict, Final, Optional
from urllib.parse import urlparse


class SecurityViolationError(Exception):
    """Исключение при нарушении протоколов безопасности."""
    pass


class PaymentGatewayClient:
    """
    Безопасный клиент для взаимодействия с платежным шлюзом.
    Включает защиту от SSRF, маскировку логов и строгую проверку SSL.
    """

    # Регулярные выражения для маскировки чувствительных данных
    SENSITIVE_PATTERNS: Final[Dict[str, str]] = {
        r'"token":\s*"[^"]+"': '"token": "***"',
        r'"card_number":\s*"\d{12}(\d{4})"': '"card_number": "**** **** **** \1"',
        r'"cvv":\s*"\d{3,4}"': '"cvv": "***"'
    }

    def __init__(self, api_token: str, base_url: str) -> None:
        self._api_token: str = api_token
        self._base_url: str = base_url.rstrip("/")
        self._logger = self._setup_logger()
        self._session = requests.Session()
        # Строгая проверка SSL-сертификатов включена по умолчанию в requests
        self._session.verify = True

    def _setup_logger(self) -> logging.Logger:
        """Настройка логгера для сессии."""
        logger = logging.getLogger("PaymentGatewayClient")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger

    def _mask_log_data(self, data: str) -> str:
        """Скрывает чувствительную информацию перед записью в лог."""
        masked_data = data
        for pattern, replacement in self.SENSITIVE_PATTERNS.items():
            masked_data = re.sub(pattern, replacement, masked_data)
        return masked_data

    def _validate_destination(self, url: str) -> None:
        """
        Защита от SSRF: проверка, что URL не указывает на внутренние адреса.
        """
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname

        if not hostname:
            raise SecurityViolationError("Invalid URL hostname")

        try:
            # Разрешаем хост в IP
            ip_address = socket.gethostbyname(hostname)
            ip_obj = ipaddress.ip_address(ip_address)

            # Проверяем, не является ли адрес приватным или локальным
            if any([ip_obj.is_private, ip_obj.is_loopback, ip_obj.is_link_local, ip_obj.is_multicast]):
                raise SecurityViolationError(f"Access to internal network address {ip_address} is forbidden")
        except socket.gaierror:
            raise SecurityViolationError(f"Could not resolve hostname: {hostname}")

    def post_payment(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправляет POST-запрос к платежному шлюзу.
        """
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        
        # 1. Проверка безопасности адреса
        self._validate_destination(url)

        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "User-Agent": "SecurePaymentClient/1.0"
        }

        # Логирование запроса с маскировкой
        raw_payload = json.dumps(payload)
        self._logger.info(f"SEND POST to {url} | Payload: {self._mask_log_data(raw_payload)}")

        try:
            response = self._session.post(
                url, 
                headers=headers, 
                data=raw_payload, 
                timeout=(3.05, 15) # connect и read timeouts
            )
            
            # Логирование ответа
            self._logger.info(f"RECV RESPONSE | Status: {response.status_code}")
            
            response.raise_for_status()
            return response.json()

        except requests.exceptions.SSLError as e:
            self._logger.error(f"SSL Verification failed for {url}")
            raise SecurityViolationError(f"Secure connection could not be established: {e}")
        except requests.exceptions.RequestException as e:
            self._logger.error(f"API Request failed: {str(e)}")
            raise