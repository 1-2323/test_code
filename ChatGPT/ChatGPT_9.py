import json
import logging
from typing import Any, Dict, Optional

import requests
from requests import Response, Session
from requests.exceptions import RequestException, Timeout


# =========================
# Исключения
# =========================

class ExternalApiError(Exception):
    """Базовое исключение клиента внешнего API."""
    pass


class ExternalApiTimeoutError(ExternalApiError):
    """Ошибка таймаута при обращении к платёжному шлюзу."""
    pass


class ExternalApiConnectionError(ExternalApiError):
    """Ошибка соединения с платёжным шлюзом."""
    pass


class ExternalApiResponseError(ExternalApiError):
    """Ошибка обработки ответа платёжного шлюза."""
    pass


# =========================
# Логирование
# =========================

def create_logger(name: str) -> logging.Logger:
    """
    Создаёт и настраивает логгер для HTTP-сессии.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


# =========================
# Клиент платёжного шлюза
# =========================

class ExternalApiClient:
    """
    Клиент для интеграции с платёжным шлюзом по HTTPS.
    """

    DEFAULT_TIMEOUT: int = 10

    def __init__(
        self,
        base_url: str,
        api_token: str,
        timeout: int = DEFAULT_TIMEOUT,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        :param base_url: базовый URL платёжного шлюза
        :param api_token: токен авторизации
        :param timeout: таймаут HTTP-запросов
        :param logger: кастомный логгер
        """
        self._base_url: str = base_url.rstrip("/")
        self._api_token: str = api_token
        self._timeout: int = timeout
        self._session: Session = requests.Session()
        self._logger: logging.Logger = logger or create_logger(self.__class__.__name__)

    # =========================
    # Публичные методы
    # =========================

    def post(
        self,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Отправляет POST-запрос к платёжному шлюзу.

        Алгоритм:
        1. Формирование URL
        2. Добавление заголовков авторизации
        3. Отправка POST-запроса
        4. Обработка JSON-ответа

        :param endpoint: путь эндпоинта
        :param payload: тело запроса
        :return: JSON-ответ в виде словаря
        """
        url: str = self._build_url(endpoint)
        headers: Dict[str, str] = self._build_headers()

        self._log_request(url, payload)

        try:
            response: Response = self._session.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            self._log_response(response)
            return self._parse_response(response)

        except Timeout as exc:
            raise ExternalApiTimeoutError(
                "Request to payment gateway timed out"
            ) from exc

        except RequestException as exc:
            raise ExternalApiConnectionError(
                "Failed to connect to payment gateway"
            ) from exc

    # =========================
    # Внутренние методы
    # =========================

    def _build_url(self, endpoint: str) -> str:
        """
        Формирует полный URL запроса.
        """
        return f"{self._base_url}/{endpoint.lstrip('/')}"

    def _build_headers(self) -> Dict[str, str]:
        """
        Формирует HTTP-заголовки.
        """
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _parse_response(self, response: Response) -> Dict[str, Any]:
        """
        Обрабатывает HTTP-ответ и извлекает JSON.
        """
        if not response.ok:
            raise ExternalApiResponseError(
                f"API returned error {response.status_code}: {response.text}"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ExternalApiResponseError(
                "Failed to decode JSON response"
            ) from exc

    def _log_request(self, url: str, payload: Dict[str, Any]) -> None:
        """
        Логирует исходящий запрос.
        """
        self._logger.info(
            "POST %s | payload=%s",
            url,
            json.dumps(payload, ensure_ascii=False),
        )

    def _log_response(self, response: Response) -> None:
        """
        Логирует входящий ответ.
        """
        self._logger.info(
            "Response %s | status=%s",
            response.url,
            response.status_code,
        )


# =========================
# Пример использования
# =========================

def example_usage() -> None:
    """
    Демонстрация использования ExternalApiClient.
    """
    client = ExternalApiClient(
        base_url="https://payments.example.com/api",
        api_token="secret-token",
    )

    response = client.post(
        endpoint="/charge",
        payload={
            "amount": 100,
            "currency": "USD",
            "source": "card_123",
        },
    )

    print(response)
