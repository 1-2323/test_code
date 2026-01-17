import ipaddress
import socket
from typing import Dict, Any, Final
from urllib.parse import urlparse

from jinja2 import Environment, select_autoescape
from weasyprint import HTML, default_url_fetcher


class PDFGenerationError(Exception):
    """Исключение для ошибок генерации документа."""
    pass


class PDFReportGenerator:
    """
    Генератор PDF-отчетов с защитой от SSRF и LFI.
    Использует Jinja2 с автоэкранированием и WeasyPrint с фильтрацией ресурсов.
    """

    def __init__(self) -> None:
        # 1. Настройка Jinja2 с автоматическим экранированием HTML-символов
        self.jinja_env = Environment(
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )

    def _safe_url_fetcher(self, url: str) -> Dict[str, Any]:
        """
        Кастомный загрузчик ресурсов для WeasyPrint.
        Блокирует локальные файлы и внутренние сетевые адреса.
        """
        parsed = urlparse(url)

        # Запрет локальных путей и схем, отличных от HTTP/HTTPS
        if parsed.scheme not in ('http', 'https'):
            raise PermissionError(f"Protocol {parsed.scheme} is forbidden for external resources.")

        hostname = parsed.hostname
        if not hostname:
            raise PermissionError("Invalid resource URL.")

        try:
            # Разрешаем DNS в IP и проверяем на приватность
            remote_ip = socket.gethostbyname(hostname)
            ip_obj = ipaddress.ip_address(remote_ip)

            if any([ip_obj.is_private, ip_obj.is_loopback, ip_obj.is_link_local]):
                raise PermissionError(f"Access to internal IP {remote_ip} is forbidden.")

        except (socket.gaierror, ValueError) as e:
            raise PermissionError(f"Could not validate resource address: {str(e)}")

        # Если проверки пройдены, используем стандартный загрузчик
        return default_url_fetcher(url)

    def generate_report(self, template_str: str, data: Dict[str, Any]) -> bytes:
        """
        Рендерит HTML-шаблон и конвертирует его в PDF.
        
        :param template_str: Строка шаблона Jinja2.
        :param data: JSON-структура данных для подстановки.
        :return: Бинарные данные PDF-файла.
        """
        try:
            # 2. Рендеринг HTML с автоматическим экранированием входных данных
            template = self.jinja_env.from_string(template_str)
            rendered_html = template.render(**data)

            # 3. Конвертация в PDF с использованием защищенного url_fetcher
            # Параметр url_fetcher ограничивает загрузку <img>, <link> и т.д.
            pdf_bytes = HTML(string=rendered_html, url_fetcher=self._safe_url_fetcher).write_pdf()
            
            return pdf_bytes

        except Exception as e:
            # В реальном приложении логируем подробности, но не отдаем их наружу
            raise PDFGenerationError(f"Failed to generate PDF: {str(e)}")


# --- Пример использования ---

report_template = """
<html>
    <head><style>body { font-family: sans-serif; }</style></head>
    <body>
        <h1>Отчет: {{ title }}</h1>
        <p>Автор: {{ author }}</p>
        <img src="{{ logo_url }}" alt="Company Logo">
        <div class="content">
            {{ description }}
        </div>
    </body>
</html>
"""

# Данные, которые могут содержать попытки XSS или SSRF
input_data = {
    "title": "Безопасный отчет",
    "author": "System Admin",
    "description": "<script>alert('XSS')</script>Данные успешно обработаны.",
    "logo_url": "https://public-cdn.example.com/logo.png"  # Пройдет проверку
    # "logo_url": "file:///etc/passwd"  -- Вызовет PermissionError
}

# generator = PDFReportGenerator()
# pdf = generator.generate_report(report_template, input_data)