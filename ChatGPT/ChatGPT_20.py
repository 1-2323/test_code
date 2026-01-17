from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field
from weasyprint import HTML


# =========================
# Pydantic-модели
# =========================

class ImageBlock(BaseModel):
    """
    Описание изображения в документе.
    """
    url: str
    alt: str = ""


class DocumentSection(BaseModel):
    """
    Секция документа.
    """
    title: str
    content: str
    images: List[ImageBlock] = Field(default_factory=list)


class DocumentPayload(BaseModel):
    """
    JSON-структура входного документа.
    """
    title: str
    author: str
    sections: List[DocumentSection]


# =========================
# Шаблонизатор HTML
# =========================

class HtmlTemplateRenderer:
    """
    Сервис рендеринга HTML из Jinja2-шаблонов.
    """

    def __init__(self, templates_dir: Path) -> None:
        self._env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Подставляет данные в HTML-шаблон.
        """
        template = self._env.get_template(template_name)
        return template.render(**context)


# =========================
# PDF-рендерер
# =========================

class PdfRenderer:
    """
    Сервис генерации PDF из HTML.
    """

    def render_to_file(
        self,
        html_content: str,
        output_path: Path,
        base_url: Path,
    ) -> None:
        """
        Рендерит PDF-файл из HTML.

        base_url нужен для загрузки внешних ресурсов
        (CSS, изображения по URL).
        """
        HTML(
            string=html_content,
            base_url=str(base_url),
        ).write_pdf(str(output_path))


# =========================
# Основной генератор отчётов
# =========================

class PdfReportGenerator:
    """
    Высокоуровневый генератор PDF-отчётов.
    """

    def __init__(
        self,
        template_renderer: HtmlTemplateRenderer,
        pdf_renderer: PdfRenderer,
    ) -> None:
        self._template_renderer = template_renderer
        self._pdf_renderer = pdf_renderer

    def generate(
        self,
        payload: DocumentPayload,
        template_name: str,
        output_file: Path,
    ) -> None:
        """
        Основной алгоритм:
        1. Подготовка контекста
        2. Рендеринг HTML
        3. Генерация PDF
        """
        context: Dict[str, Any] = {
            "title": payload.title,
            "author": payload.author,
            "sections": payload.sections,
        }

        html: str = self._template_renderer.render(
            template_name=template_name,
            context=context,
        )

        self._pdf_renderer.render_to_file(
            html_content=html,
            output_path=output_file,
            base_url=Path.cwd(),
        )


# =========================
# Пример использования
# =========================

def example_usage() -> None:
    """
    Демонстрация генерации PDF-отчёта.
    """
    payload = DocumentPayload(
        title="Monthly Report",
        author="Analytics Team",
        sections=[
            DocumentSection(
                title="Overview",
                content="This is the monthly performance overview.",
                images=[
                    ImageBlock(
                        url="https://via.placeholder.com/300",
                        alt="Chart",
                    )
                ],
            ),
            DocumentSection(
                title="Conclusion",
                content="Results are above expectations.",
            ),
        ],
    )

    templates_dir = Path("./templates")
    output_pdf = Path("./report.pdf")

    template_renderer = HtmlTemplateRenderer(templates_dir)
    pdf_renderer = PdfRenderer()

    generator = PdfReportGenerator(
        template_renderer=template_renderer,
        pdf_renderer=pdf_renderer,
    )

    generator.generate(
        payload=payload,
        template_name="report.html",
        output_file=output_pdf,
    )
