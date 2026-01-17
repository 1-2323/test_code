import ipaddress
import json
import re
from typing import Any, Dict
from urllib.parse import urlparse

import requests
from jinja2 import Environment, BaseLoader, select_autoescape
from weasyprint import HTML, default_url_fetcher


# =========================
# EXCEPTIONS
# =========================

class PdfGenerationError(Exception):
    pass


# =========================
# SECURITY UTILITIES
# =========================

def is_private_address(hostname: str) -> bool:
    """
    Блокирует localhost и внутренние сетевые адреса.
    """
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_reserved
    except ValueError:
        return False


def validate_external_url(url: str) -> None:
    """
    Запрещает file://, localhost и внутренние сети.
    """
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise PdfGenerationError("Недопустимая схема URL")

    if not parsed.hostname or is_private_address(parsed.hostname):
        raise PdfGenerationError("Доступ к внутренним ресурсам запрещён")


# =========================
# SAFE URL FETCHER
# =========================

def secure_url_fetcher(url: str) -> Dict[str, Any]:
    """
    Безопасный загрузчик ресурсов для WeasyPrint.
    Разрешает только внешние HTTP(S) изображения.
    """
    validate_external_url(url)

    response = requests.get(url, timeout=5)
    response.raise_for_status()

    return {
        "string": response.content,
        "mime_type": response.headers.get("Content-Type"),
        "encoding": "binary",
        "redirected_url": url,
    }


# =========================
# PDF GENERATOR
# =========================

class PdfReportGenerator:
    """
    Генератор PDF-отчётов на основе JSON и HTML-шаблона.
    """

    def __init__(self, html_template: str) -> None:
        self._env = Environment(
            loader=BaseLoader(),
            autoescape=select_autoescape(enabled_extensions=("html",)),
        )
        self._template = self._env.from_string(html_template)

    def generate(self, document_data: Dict[str, Any]) -> bytes:
        """
        Рендерит PDF из JSON-структуры.
        """
        if not isinstance(document_data, dict):
            raise PdfGenerationError("Некорректная структура документа")

        html_content = self._template.render(document=document_data)

        try:
            pdf = HTML(
                string=html_content,
                url_fetcher=secure_url_fetcher,
            ).write_pdf()
        except Exception as exc:
            raise PdfGenerationError("Ошибка генерации PDF") from exc

        return pdf


# =========================
# EXAMPLE TEMPLATE (INLINE)
# =========================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ document.title }}</title>
</head>
<body>
    <h1>{{ document.title }}</h1>
    <p>{{ document.description }}</p>

    {% if document.image_url %}
        <img src="{{ document.image_url }}" alt="Image"/>
    {% endif %}
</body>
</html>
"""


# =========================
# INITIALIZATION
# =========================

pdf_generator = PdfReportGenerator(HTML_TEMPLATE)
