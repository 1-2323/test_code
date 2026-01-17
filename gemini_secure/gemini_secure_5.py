import requests
import ipaddress
import socket
from typing import Dict, Any, Final, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup


class SSRFViolationError(Exception):
    """Исключение при попытке обращения к запрещенному сетевому адресу."""
    pass


class LinkPreviewer:
    """
    Сервис для безопасного извлечения метаданных веб-страниц.
    Защищен от SSRF, бесконечных загрузок и зависаний соединения.
    """

    # Константы ограничений
    TIMEOUT: Final[int] = 5  # секунд
    MAX_CONTENT_SIZE: Final[int] = 1024 * 512  # 512 КБ (достаточно для head)
    USER_AGENT: Final[str] = "LinkPreviewerBot/1.0"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})

    def _is_safe_url(self, url: str) -> bool:
        """
        Проверяет URL на принадлежность к публичным адресам.
        Блокирует localhost, частные подсети (192.168.x.x и др.) и loopback.
        """
        try:
            parsed_url = urlparse(url)
            if parsed_url.scheme not in ("http", "https"):
                return False

            hostname = parsed_url.hostname
            if not hostname:
                return False

            # Разрешаем DNS имя в IP адрес
            remote_ip = socket.gethostbyname(hostname)
            ip_obj = ipaddress.ip_address(remote_ip)

            # Проверка: адрес не должен быть локальным, частным или многоадресным
            if any([
                ip_obj.is_loopback,
                ip_obj.is_private,
                ip_obj.is_multicast,
                ip_obj.is_reserved,
                ip_obj.is_link_local
            ]):
                return False

            return True
        except (socket.gaierror, ValueError):
            return False

    def get_preview(self, url: str) -> Dict[str, Any]:
        """
        Запрашивает URL, извлекает Title и Description.
        
        :param url: Целевой URL для предпросмотра.
        :return: JSON-совместимый словарь с метаданными.
        :raises SSRFViolationError: Если URL ведет во внутреннюю сеть.
        """
        if not self._is_safe_url(url):
            raise SSRFViolationError(f"Access to the provided URL is forbidden: {url}")

        try:
            # Используем stream=True для контроля размера данных
            with self.session.get(url, timeout=self.TIMEOUT, stream=True) as response:
                response.raise_for_status()

                # Проверка размера контента через Header (если есть)
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > self.MAX_CONTENT_SIZE:
                    raise ValueError("Resource too large")

                # Чтение только первых MAX_CONTENT_SIZE байт
                raw_html = response.raw.read(self.MAX_CONTENT_SIZE, decode_content=True)
                
                return self._parse_metadata(raw_html.decode('utf-8', errors='ignore'))

        except requests.exceptions.Timeout:
            return {"error": "Connection timed out", "url": url}
        except requests.exceptions.RequestException as e:
            return {"error": f"Failed to fetch metadata: {str(e)}", "url": url}
        except Exception as e:
            return {"error": f"Internal error: {str(e)}", "url": url}

    def _parse_metadata(self, html_content: str) -> Dict[str, Any]:
        """Парсит HTML и извлекает базовые теги."""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Получение заголовка
        title = soup.title.string if soup.title else ""
        
        # Поиск описания в мета-тегах
        description = ""
        desc_tag = (
            soup.find("meta", attrs={"name": "description"}) or 
            soup.find("meta", attrs={"property": "og:description"})
        )
        if desc_tag and isinstance(desc_tag, Dict): # MyPy check
            description = desc_tag.get("content", "")
        elif desc_tag:
            description = desc_tag.get("content", "")

        return {
            "title": title.strip() if title else None,
            "description": str(description).strip() if description else None
        }