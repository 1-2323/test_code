import io
import json
import logging
from typing import Dict, Any, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML, default_url_fetcher

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PDFGenerator")

class ReportGenerator:
    """
    Сервис генерации PDF-отчетов на основе JSON-структур.
    Использует HTML/CSS шаблоны и поддерживает внешние изображения.
    """

    def __init__(self, templates_path: str = "templates"):
        """
        Инициализация окружения Jinja2.
        """
        self.env = Environment(
            loader=FileSystemLoader(templates_path),
            autoescape=select_autoescape(['html', 'xml'])
        )

    def _custom_url_fetcher(self, url: str) -> Dict[str, Any]:
        """
        Обработчик загрузки внешних ресурсов (изображений).
        Позволяет контролировать доступ к внешним URL.
        """
        logger.info(f"Загрузка ресурса: {url}")
        return default_url_fetcher(url)

    def render_pdf(self, template_name: str, data: Dict[str, Any]) -> bytes:
        """
        Основной метод рендеринга.
        
        Логика работы:
        1. Загрузка HTML-шаблона.
        2. Подстановка данных через Jinja2.
        3. Рендеринг HTML в PDF через WeasyPrint.
        """
        try:
            # 1. Генерация HTML из шаблона
            template = self.env.get_template(template_name)
            html_content = template.render(**data)

            # 2. Рендеринг в PDF (в память)
            pdf_buffer = io.BytesIO()
            HTML(
                string=html_content, 
                url_fetcher=self._custom_url_fetcher
            ).write_pdf(pdf_buffer)

            logger.info("PDF успешно сформирован.")
            return pdf_buffer.getvalue()

        except Exception as e:
            logger.error(f"Ошибка при генерации отчета: {str(e)}")
            raise RuntimeError(f"Сбой рендеринга PDF: {e}")

# --- Пример реализации и данных ---

if __name__ == "__main__":
    # 1. Пример входного JSON
    report_data_json = """
    {
        "report_title": "Ежемесячный аналитический отчет",
        "date": "2026-01-17",
        "author": "Gemini System",
        "summary": "Продажи выросли на 15% благодаря автоматизации.",
        "logo_url": "https://www.python.org/static/img/python-logo.png",
        "metrics": [
            {"name": "Трафик", "value": "12,400"},
            {"name": "Конверсия", "value": "3.2%"}
        ]
    }
    """
    
    # 2. Имитация шаблона (в реальности лежит в файле .html)
    # <html><body>
    #   <h1>{{ report_title }}</h1>
    #   <img src="{{ logo_url }}" style="width: 100px;">
    #   <p>Автор: {{ author }}</p>
    #   <ul>
    #     {% for m in metrics %}
    #       <li>{{ m.name }}: {{ m.value }}</li>
    #     {% endfor %}
    #   </ul>
    # </body></html>

    # Инициализация сервиса
    # generator = ReportGenerator(templates_path="./my_templates")
    
    # Парсинг данных
    data = json.loads(report_data_json)
    
    print("Генератор готов к обработке JSON и рендерингу в PDF.")
    # pdf_bytes = generator.render_pdf("report_template.html", data)