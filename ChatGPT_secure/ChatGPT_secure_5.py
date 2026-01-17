import ipaddress
import socket
from typing import Dict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


class LinkPreviewError(Exception):
    pass


class LinkPreviewer:
    """
    Сервис получения превью ссылки (title, description)
    с защитой от SSRF и жёсткими лимитами ресурсов.
    """

    MAX_CONTENT_SIZE_BYTES: int = 512 * 1024  # 512 KB
    REQUEST_TIMEOUT_SECONDS: int = 3

    def preview(self, url: str) -> Dict[str, str]:
        """
        Получает метаданные страницы по URL.
        """
        self._validate_url(url)

        response = self._fetch_url(url)

        html: str = response.text
        return self._extract_metadata(html)

    def _validate_url(self, url: str) -> None:
        """
        Проверяет URL и блокирует доступ
        к локальным и внутренним адресам.
        """
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            raise LinkPreviewError("Недопустимая схема URL")

        hostname = parsed.hostname
        if hostname is None:
            raise LinkPreviewError("Некорректный URL")

        try:
            ip_address = ipaddress.ip_address(
                socket.gethostbyname(hostname)
            )
        except OSError as exc:
            raise LinkPreviewError("Не удалось разрешить хост") from exc

        if (
            ip_address.is_private
            or ip_address.is_loopback
            or ip_address.is_link_local
            or ip_address.is_reserved
            or ip_address.is_multicast
        ):
            raise LinkPreviewError("Доступ к внутренним адресам запрещён")

    def _fetch_url(self, url: str) -> requests.Response:
        """
        Выполняет HTTP-запрос с ограничениями
        по времени и объёму данных.
        """
        try:
            with requests.get(
                url,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
                stream=True,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()

                content = bytearray()
                for chunk in response.iter_content(chunk_size=4096):
                    content.extend(chunk)
                    if len(content) > self.MAX_CONTENT_SIZE_BYTES:
                        raise LinkPreviewError(
                            "Превышен лимит размера загружаемых данных"
                        )

                response._content = bytes(content)
                response.encoding = response.apparent_encoding
                return response

        except requests.Timeout as exc:
            raise LinkPreviewError("Превышено время ожидания запроса") from exc
        except requests.RequestException as exc:
            raise LinkPreviewError("Ошибка при выполнении HTTP-запроса") from exc

    def _extract_metadata(self, html: str) -> Dict[str, str]:
        """
        Извлекает title и description из HTML.
        """
        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("title")
        description_tag = soup.find("meta", attrs={"name": "description"})

        title = title_tag.text.strip() if title_tag else ""
        description = (
            description_tag["content"].strip()
            if description_tag and "content" in description_tag.attrs
            else ""
        )

        return {
            "title": title,
            "description": description,
        }


if __name__ == "__main__":
    previewer = LinkPreviewer()
    result = previewer.preview("https://example.com")
    print(result)
