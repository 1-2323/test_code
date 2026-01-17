import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict
from urllib.parse import urlparse
from pydantic import BaseModel, HttpUrl, ValidationError
from requests.exceptions import RequestException, Timeout, ConnectionError


# --- Модели данных ---

class LinkMetadata(BaseModel):
    """Схема ответа с метаданными страницы."""
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    status_code: int


# --- Исключения ---

class LinkPreviewError(Exception):
    """Базовое исключение для сервиса превью ссылок."""
    pass


# --- Логика сервиса ---

class LinkPreviewer:
    """
    Сервис для извлечения метаданных из веб-страниц.
    
    Attributes:
        timeout (int): Время ожидания ответа от сервера в секундах.
        user_agent (str): Заголовок User-Agent для имитации браузера.
    """

    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
        }

    def _validate_url(self, url: str) -> bool:
        """Проверяет корректность формата URL."""
        try:
            parsed = urlparse(url)
            return all([parsed.scheme, parsed.netloc])
        except Exception:
            return False

    def get_preview(self, url: str) -> Dict[str, Optional[str | int]]:
        """
        Загружает страницу и извлекает заголовок и описание.

        Args:
            url: Целевой URL для анализа.

        Returns:
            Dict: Словарь с метаданными.

        Raises:
            LinkPreviewError: Если URL некорректен или произошла ошибка сети.
        """
        if not self._validate_url(url):
            raise LinkPreviewError(f"Некорректный URL: {url}")

        try:
            # Выполнение GET-запроса с обработкой таймаутов
            response = requests.get(
                url, 
                headers=self.headers, 
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()

        except Timeout:
            raise LinkPreviewError("Превышено время ожидания ответа от сервера.")
        except ConnectionError:
            raise LinkPreviewError("Ошибка соединения с сервером.")
        except RequestException as e:
            raise LinkPreviewError(f"Сетевая ошибка: {str(e)}")

        # Парсинг HTML содержимого
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Извлечение Title
        title = soup.title.string.strip() if soup.title else None
        
        # Извлечение Description (из мета-тегов)
        description = None
        desc_tag = (
            soup.find("meta", attrs={"name": "description"}) or 
            soup.find("meta", attrs={"property": "og:description"})
        )
        if desc_tag and isinstance(desc_tag, dict): # Типизация для BS4
             description = desc_tag.get("content", "").strip()
        elif desc_tag:
             description = desc_tag.get("content", "").strip()

        # Формирование валидированного ответа через Pydantic
        metadata = LinkMetadata(
            url=url,
            title=title,
            description=description,
            status_code=response.status_code
        )

        return metadata.model_dump()


# --- Пример использования ---

if __name__ == "__main__":
    previewer = LinkPreviewer(timeout=3)
    
    test_urls = [
        "https://www.python.org",
        "https://github.com",
        "invalid-url"
    ]

    for target in test_urls:
        print(f"\nАнализ: {target}")
        try:
            data = previewer.get_preview(target)
            print(f"Результат: {data}")
        except LinkPreviewError as err:
            print(f"Ошибка сервиса: {err}")