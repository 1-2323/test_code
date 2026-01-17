import ipaddress
import json
import logging
import socket
from typing import Any, Dict
from urllib.parse import urlparse

import requests
from requests import Session, Response
from requests.exceptions import RequestException, Timeout


class ExternalApiClientError(Exception):
    pass


class ExternalApiClientSecurityError(ExternalApiClientError):
    pass


class ExternalApiClient:
    """
    Клиент для интеграции с внешним платёжным шлюзом по HTTPS.
    """

    REQUEST_TIMEOUT_SECONDS = 5

    def __init__(self, base_url: str, api_token: str) -> None:
        self._base_url: str = base_url.rstrip("/")
        self._api_token: str = api_token
        self._session: Session = self._create_session()
        self._logger = self._configure_logger()

        self._validate_base_url(self._base_url)

    def post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправляет POST-запрос к платёжному шлюзу.
        """
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        self._validate_url(url)

        self._log_request(url, payload)

        try:
            response: Response = self._session.post(
                url=url,
                json=payload,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
                verify=True,
            )
            response.raise_for_status()
        except Timeout as exc:
            raise ExternalApiClientError("Превышено время ожидания запроса") from exc
        except RequestException as exc:
            raise ExternalApiClientError("Ошибка HTTP-запроса") from exc

        return self._handle_response(response)

    def _create_session(self) -> Session:
        """
        Создаёт HTTP-сессию с преднастроенными заголовками.
        """
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {self._api_token}",
                "Content-Type": "application/json",
            }
        )
        return session

    def _handle_response(self, response: Response) -> Dict[str, Any]:
        """
        Обрабатывает JSON-ответ от API.
        """
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ExternalApiClientError("Ответ не является валидным JSON") from exc

        self._log_response(response.status_code, data)
        return data

    def _validate_base_url(self, url: str) -> None:
        """
        Проверяет базовый URL при инициализации клиента.
        """
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ExternalApiClientSecurityError("Разрешены только HTTPS-соединения")

    def _validate_url(self, url: str) -> None:
        """
        Блокирует обращения к внутренним и локальным адресам.
        """
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            raise ExternalApiClientSecurityError("Некорректный URL")

        try:
            ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        except OSError as exc:
            raise ExternalApiClientSecurityError("Не удалось разрешить хост") from exc

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_reserved
            or ip.is_link_local
            or ip.is_multicast
        ):
            raise ExternalApiClientSecurityError(
                "Доступ к внутренним адресам запрещён"
            )

    def _configure_logger(self) -> logging.Logger:
        """
        Настраивает кастомный логгер с маскированием чувствительных данных.
        """
        logger = logging.getLogger("ExternalApiClient")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def _log_request(self, url: str, payload: Dict[str, Any]) -> None:
        """
        Логирует исходящий запрос с маскированием данных.
        """
        masked_payload = self._mask_sensitive_fields(payload)
        self._logger.info(
            "REQUEST POST %s | payload=%s",
            url,
            json.dumps(masked_payload, ensure_ascii=False),
        )

    def _log_response(self, status_code: int, data: Dict[str, Any]) -> None:
        """
        Логирует ответ от API с маскированием данных.
        """
        masked_data = self._mask_sensitive_fields(data)
        self._logger.info(
            "RESPONSE status=%s | body=%s",
            status_code,
            json.dumps(masked_data, ensure_ascii=False),
        )

    def _mask_sensitive_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Маскирует чувствительные поля в логах.
        """
        sensitive_keys = {"card_number", "cvv", "token", "api_key"}

        masked: Dict[str, Any] = {}
        for key, value in data.items():
            if key.lower() in sensitive_keys:
                masked[key] = "***MASKED***"
            else:
                masked[key] = value

        return masked
