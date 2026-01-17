from typing import Dict, Optional

import requests
from requests import Response
from requests.exceptions import Timeout, RequestException
from bs4 import BeautifulSoup


# =========================
# Исключения
# =========================

class LinkPreviewError(Exception):
    """Базовое исключение сервиса предпросмотра ссылок."""
    pass


class LinkTimeoutError(LinkPreviewError):
    """Ошибка таймаута при обращении к URL."""
    pass


class LinkConnectionError(LinkPreviewError):
    """Ошибка соединения при обращении к URL."""
    pass


# =========================
# Сервис предпросмотра ссылок
# =========================

class LinkPreviewer:
    """
    Сервис для получения метаданных страницы по URL.
    """

    DEFAULT_TIMEOUT: int = 5

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        """
        :param timeout: таймаут HTTP-запроса в секундах
        """
        self._timeout: int = timeout

    def preview(self, url: str) -> Dict[str, Optional[str]]:
        """
        Получает метаданные страницы (title, description).

        Алгоритм:
        1. Выполняет HTTP-запрос к URL
        2. Парсит HTML-страницу
        3. Извлекает title и description
        4. Возвращает результат в виде JSON-совместимого словаря

        :param url: URL страницы
        :return: словарь с метаданными
        """
        response: Response = self._fetch_page(url)
        return self._extract_metadata(response.text)

    def _fetch_page(self, url: str) -> Response:
        """
        Выполняет HTTP-запрос к странице.
        """
        try:
            response: Response = requests.get(url, timeout=self._timeout)
            response.raise_for_status()
            return response

        except Timeout as exc:
            raise LinkTimeoutError(
                f"Timeout while fetching URL: {url}"
            ) from exc

        except RequestException as exc:
            raise LinkConnectionError(
                f"Connection error while fetching URL: {url}"
            ) from exc

    @staticmethod
    def _extract_metadata(html: str) -> Dict[str, Optional[str]]:
        """
        Извлекает метаданные из HTML.
        """
        soup: BeautifulSoup = BeautifulSoup(html, "html.parser")

        title: Optional[str] = (
            soup.title.string.strip()
            if soup.title and soup.title.string
            else None
        )

        description_tag = soup.find("meta", attrs={"name": "description"})
        description: Optional[str] = (
            description_tag.get("content").strip()
            if description_tag and description_tag.get("content")
            else None
        )

        return {
            "title": title,
            "description": description,
        }
