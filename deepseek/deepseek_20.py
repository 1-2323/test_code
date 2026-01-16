import json
from typing import Dict, Any, List, Optional, BinaryIO
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import io
import base64

from jinja2 import Environment, FileSystemLoader, Template
import requests
from PIL import Image
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as ReportLabImage, PageBreak, ListFlowable, ListItem,
    KeepTogether
)
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY


@dataclass
class DocumentSection:
    """Секция документа"""
    type: str  # "text", "image", "table", "list"
    content: Any
    style: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class DocumentStructure:
    """Структура документа"""
    title: str
    author: Optional[str] = None
    subject: Optional[str] = None
    keywords: Optional[List[str]] = None
    sections: Optional[List[DocumentSection]] = None
    styles: Optional[Dict[str, Any]] = None


class ImageLoader:
    """Загрузчик изображений"""
    
    @staticmethod
    def load_image_from_url(url: str) -> Optional[Image.Image]:
        """Загрузить изображение по URL"""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            image_data = io.BytesIO(response.content)
            image = Image.open(image_data)
            
            return image.convert('RGB')  # Конвертируем в RGB для PDF
            
        except Exception as e:
            print(f"Ошибка загрузки изображения {url}: {str(e)}")
            return None
    
    @staticmethod
    def load_image_from_base64(base64_data: str) -> Optional[Image.Image]:
        """Загрузить изображение из base64 строки"""
        try:
            # Убираем префикс data:image если есть
            if 'base64,' in base64_data:
                base64_data = base64_data.split('base64,')[1]
            
            image_data = base64.b64decode(base64_data)
            image = Image.open(io.BytesIO(image_data))
            
            return image.convert('RGB')
            
        except Exception as e:
            print(f"Ошибка загрузки base64 изображения: {str(e)}")
            return None
    
    @staticmethod
    def resize_image(
        image: Image.Image,
        max_width: int = 500,
        max_height: int = 500
    ) -> Image.Image:
        """Изменить размер изображения"""
        width, height = image.size
        
        # Рассчитываем новые размеры с сохранением пропорций
        if width > max_width or height > max_height:
            ratio = min(max_width / width, max_height / height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            
            return image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        return image


class PDFGenerator:
    """Генератор PDF документов"""
    
    def __init__(
        self,
        template_dir: Optional[str] = None,
        default_page_size: str = "A4",
        default_font: str = "Helvetica"
    ):
        self.template_dir = template_dir
        self.default_page_size = A4 if default_page_size == "A4" else letter
        self.default_font = default_font
        
        # Инициализация Jinja2 окружения
        if template_dir:
            self.jinja_env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=True
            )
        else:
            self.jinja_env = Environment(loader=FileSystemLoader('.'))
        
        # Загрузчик изображений
        self.image_loader = ImageLoader()
        
        # Стили по умолчанию
        self.styles = self._create_default_styles()
    
    def generate_from_json(
        self,
        json_structure: Dict[str, Any],
        output_path: str
    ) -> bool:
        """
        Сгенерировать PDF из JSON структуры
        
        Args:
            json_structure: Структура документа в JSON
            output_path: Путь для сохранения PDF
            
        Returns:
            Успех операции
        """
        try:
            # 1. Парсим структуру документа
            document = self._parse_document_structure(json_structure)
            
            # 2. Создаем PDF документ
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                pdf_buffer,
                pagesize=self.default_page_size,
                title=document.title,
                author=document.author or "",
                subject=document.subject or ""
            )
            
            # 3. Генерируем содержимое документа
            story = self._build_document_story(document)
            
            # 4. Собираем PDF
            doc.build(story)
            
            # 5. Сохраняем в файл
            pdf_buffer.seek(0)
            with open(output_path, 'wb') as f:
                f.write(pdf_buffer.read())
            
            print(f"PDF успешно сгенерирован: {output_path}")
            return True
            
        except Exception as e:
            print(f"Ошибка генерации PDF: {str(e)}")
            return False
    
    def generate_from_template(
        self,
        template_name: str,
        template_data: Dict[str, Any],
        output_path: str
    ) -> bool:
        """
        Сгенерировать PDF из HTML шаблона
        
        Args:
            template_name: Имя HTML шаблона
            template_data: Данные для подстановки в шаблон
            output_path: Путь для сохранения PDF
            
        Returns:
            Успех операции
        """
        try:
            # 1. Рендерим HTML шаблон
            template = self.jinja_env.get_template(template_name)
            html_content = template.render(**template_data)
            
            # 2. Преобразуем HTML в структуру документа
            # В реальном приложении здесь нужен парсер HTML
            # Для примера используем упрощенную логику
            document_structure = self._html_to_document_structure(
                html_content,
                template_data.get('title', 'Документ')
            )
            
            # 3. Генерируем PDF
            return self.generate_from_json(
                asdict(document_structure),
                output_path
            )
            
        except Exception as e:
            print(f"Ошибка генерации из шаблона: {str(e)}")
            return False
    
    def _parse_document_structure(
        self, 
        json_data: Dict[str, Any]
    ) -> DocumentStructure:
        """Парсинг структуры документа из JSON"""
        sections = []
        
        for section_data in json_data.get('sections', []):
            section = DocumentSection(
                type=section_data['type'],
                content=section_data['content'],
                style=section_data.get('style'),
                metadata=section_data.get('metadata')
            )
            sections.append(section)
        
        return DocumentStructure(
            title=json_data.get('title', 'Без названия'),
            author=json_data.get('author'),
            subject=json_data.get('subject'),
            keywords=json_data.get('keywords', []),
            sections=sections,
            styles=json_data.get('styles')
        )
    
    def _build_document_story(
        self, 
        document: DocumentStructure
    ) -> List[Any]:
        """Построение содержимого документа для ReportLab"""
        story = []
        
        # Добавляем заголовок
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            alignment=TA_CENTER,
            spaceAfter=30
        )
        
        story.append(Paragraph(document.title, title_style))
        
        # Добавляем метаданные, если есть
        if document.author or document.subject:
            meta_text = []
            if document.author:
                meta_text.append(f"Автор: {document.author}")
            if document.subject:
                meta_text.append(f"Тема: {document.subject}")
            if document.keywords:
                meta_text.append(f"Ключевые слова: {', '.join(document.keywords)}")
            
            meta_style = ParagraphStyle(
                'MetaStyle',
                parent=self.styles['Normal'],
                fontSize=9,
                textColor=colors.grey,
                alignment=TA_CENTER,
                spaceAfter=20
            )
            
            story.append(Paragraph('<br/>'.join(meta_text), meta_style))
        
        # Добавляем разделитель
        story.append(Spacer(1, 20))
        
        # Обрабатываем секции
        for section in document.sections or []:
            section_elements = self._process_section(section)
            story.extend(section_elements)
        
        return story
    
    def _process_section(
        self, 
        section: DocumentSection
    ) -> List[Any]:
        """Обработка отдельной секции документа"""
        elements = []
        
        if section.type == "text":
            elements.extend(self._process_text_section(section))
        
        elif section.type == "image":
            elements.extend(self._process_image_section(section))
        
        elif section.type == "table":
            elements.extend(self._process_table_section(section))
        
        elif section.type == "list":
            elements.extend(self._process_list_section(section))
        
        # Добавляем отступ после секции
        if elements:
            elements.append(Spacer(1, 15))
        
        return elements
    
    def _process_text_section(
        self, 
        section: DocumentSection
    ) -> List[Any]:
        """Обработка текстовой секции"""
        elements = []
        
        # Применяем стиль
        style_name = section.style.get('style', 'Normal') if section.style else 'Normal'
        style = self._get_paragraph_style(section.style or {})
        
        # Разделяем текст на параграфы
        paragraphs = str(section.content).split('\n\n')
        
        for paragraph in paragraphs:
            if paragraph.strip():
                # Обрабатываем вложенные параграфы
                for line in paragraph.split('\n'):
                    if line.strip():
                        p = Paragraph(line.strip(), style)
                        elements.append(p)
                elements.append(Spacer(1, 6))
        
        return elements
    
    def _process_image_section(
        self, 
        section: DocumentSection
    ) -> List[Any]:
        """Обработка секции с изображением"""
        elements = []
        
        image_content = section.content
        metadata = section.metadata or {}
        
        # Загружаем изображение
        image = None
        
        if isinstance(image_content, str):
            if image_content.startswith('http'):
                # Изображение по URL
                image = self.image_loader.load_image_from_url(image_content)
            elif 'base64' in image_content:
                # Изображение в base64
                image = self.image_loader.load_image_from_base64(image_content)
            else:
                # Локальный файл
                try:
                    image = Image.open(image_content)
                except:
                    print(f"Не удалось загрузить изображение: {image_content}")
        
        if not image:
            # Создаем заглушку для изображения
            placeholder = f"[Изображение не загружено: {image_content}]"
            elements.append(Paragraph(placeholder, self.styles['Italic']))
            return elements
        
        # Изменяем размер, если нужно
        max_width = metadata.get('max_width', 500)
        max_height = metadata.get('max_height', 500)
        image = self.image_loader.resize_image(image, max_width, max_height)
        
        # Сохраняем изображение во временный буфер
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='JPEG', quality=85)
        img_buffer.seek(0)
        
        # Создаем объект изображения для ReportLab
        img_width = image.width * 0.75  # Конвертация пикселей в пункты
        img_height = image.height * 0.75
        
        reportlab_image = ReportLabImage(img_buffer, width=img_width, height=img_height)
        
        # Добавляем подпись, если есть
        caption = metadata.get('caption')
        if caption:
            caption_style = ParagraphStyle(
                'Caption',
                parent=self.styles['Normal'],
                fontSize=9,
                textColor=colors.grey,
                alignment=TA_CENTER
            )
            elements.append(reportlab_image)
            elements.append(Paragraph(caption, caption_style))
        else:
            elements.append(reportlab_image)
        
        return elements
    
    def _process_table_section(
        self, 
        section: DocumentSection
    ) -> List[Any]:
        """Обработка табличной секции"""
        table_data = section.content
        
        if not table_data or not isinstance(table_data, list):
            return [Paragraph("Некорректные данные таблицы", self.styles['Italic'])]
        
        # Создаем таблицу
        table = Table(
            table_data,
            colWidths=section.metadata.get('col_widths') if section.metadata else None,
            rowHeights=section.metadata.get('row_heights') if section.metadata else None
        )
        
        # Применяем стиль таблицы
        table_style = TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.black),
            ('BOX', (0, 0), (-1, -1), 0.25, colors.black),
        ])
        
        # Добавляем стиль заголовка, если есть
        if section.metadata and section.metadata.get('header_row', True):
            table_style.add('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey)
            table_style.add('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')
        
        table.setStyle(table_style)
        
        return [table]
    
    def _process_list_section(
        self, 
        section: DocumentSection
    ) -> List[Any]:
        """Обработка списковой секции"""
        list_items = section.content
        
        if not isinstance(list_items, list):
            list_items = [list_items]
        
        bullet_style = ListFlowable(
            [
                ListItem(
                    Paragraph(str(item), self.styles['Normal']),
                    leftIndent=20
                )
                for item in list_items
            ],
            bulletType='bullet',
            leftIndent=30
        )
        
        return [bullet_style]
    
    def _create_default_styles(self) -> Dict[str, ParagraphStyle]:
        """Создание стилей по умолчанию"""
        styles = getSampleStyleSheet()
        
        # Добавляем кастомные стили
        custom_styles = {
            'Title': ParagraphStyle(
                'CustomTitle',
                parent=styles['Title'],
                fontSize=24,
                leading=28,
                alignment=TA_CENTER,
                spaceAfter=30
            ),
            'Heading1': ParagraphStyle(
                'CustomHeading1',
                parent=styles['Heading1'],
                fontSize=18,
                leading=22,
                spaceBefore=20,
                spaceAfter=10
            ),
            'Heading2': ParagraphStyle(
                'CustomHeading2',
                parent=styles['Heading2'],
                fontSize=16,
                leading=20,
                spaceBefore=15,
                spaceAfter=8
            ),
            'Normal': ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontSize=11,
                leading=15,
                spaceAfter=6,
                alignment=TA_JUSTIFY
            ),
            'Italic': ParagraphStyle(
                'CustomItalic',
                parent=styles['Italic'],
                fontSize=11,
                leading=15,
                spaceAfter=6
            )
        }
        
        styles.add(custom_styles)
        return styles
    
    def _get_paragraph_style(
        self, 
        style_config: Dict[str, Any]
    ) -> ParagraphStyle:
        """Получить стиль параграфа из конфигурации"""
        base_style_name = style_config.get('base_style', 'Normal')
        base_style = self.styles.get(base_style_name, self.styles['Normal'])
        
        # Создаем кастомный стиль на основе базового
        custom_style = ParagraphStyle(
            f'DynamicStyle_{id(style_config)}',
            parent=base_style
        )
        
        # Применяем настройки стиля
        if 'font_size' in style_config:
            custom_style.fontSize = style_config['font_size']
        if 'text_color' in style_config:
            custom_style.textColor = self._parse_color(style_config['text_color'])
        if 'alignment' in style_config:
            alignment_map = {
                'left': TA_LEFT,
                'center': TA_CENTER,
                'right': TA_RIGHT,
                'justify': TA_JUSTIFY
            }
            custom_style.alignment = alignment_map.get(
                style_config['alignment'].lower(),
                TA_JUSTIFY
            )
        if 'space_before' in style_config:
            custom_style.spaceBefore = style_config['space_before']
        if 'space_after' in style_config:
            custom_style.spaceAfter = style_config['space_after']
        
        return custom_style
    
    def _parse_color(self, color_str: str) -> colors.Color:
        """Парсинг цвета из строки"""
        color_map = {
            'black': colors.black,
            'white': colors.white,
            'red': colors.red,
            'green': colors.green,
            'blue': colors.blue,
            'grey': colors.grey,
            'lightgrey': colors.lightgrey,
            'darkgrey': colors.darkgrey
        }
        
        if color_str in color_map:
            return color_map[color_str]
        
        # Попробуем парсить hex
        if color_str.startswith('#'):
            try:
                return colors.HexColor(color_str)
            except:
                pass
        
        return colors.black
    
    def _html_to_document_structure(
        self,
        html_content: str,
        title: str
    ) -> DocumentStructure:
        """
        Конвертация HTML в структуру документа
        В реальном приложении нужно использовать полноценный парсер HTML
        """
        # Упрощенная реализация для примера
        sections = []
        
        # Разделяем HTML на параграфы (упрощенно)
        lines = html_content.split('\n')
        current_text = []
        
        for line in lines:
            line = line.strip()
            if line:
                if line.startswith('<img'):
                    # Изображение
                    if current_text:
                        sections.append(DocumentSection(
                            type="text",
                            content='\n'.join(current_text)
                        ))
                        current_text = []
                    
                    # Упрощенный парсинг тега img
                    sections.append(DocumentSection(
                        type="image",
                        content="https://example.com/image.jpg",  # В реальности извлекаем src
                        metadata={"caption": "Изображение из HTML"}
                    ))
                elif line.startswith('<table'):
                    # Таблица (упрощенно)
                    sections.append(DocumentSection(
                        type="table",
                        content=[["Ячейка 1", "Ячейка 2"], ["Ячейка 3", "Ячейка 4"]]
                    ))
                else:
                    # Текст
                    current_text.append(line)
        
        if current_text:
            sections.append(DocumentSection(
                type="text",
                content='\n'.join(current_text)
            ))
        
        return DocumentStructure(
            title=title,
            sections=sections
        )


# Пример использования
if __name__ == "__main__":
    # Пример JSON структуры документа
    example_json = {
        "title": "Ежеквартальный отчет",
        "author": "Иван Петров",
        "subject": "Финансовые показатели Q3 2024",
        "keywords": ["отчет", "финансы", "Q3", "2024"],
        "sections": [
            {
                "type": "text",
                "content": "Это введение к отчету. В данном разделе представлены основные финансовые показатели компании за третий квартал 2024 года.",
                "style": {
                    "base_style": "Normal",
                    "alignment": "justify"
                }
            },
            {
                "type": "table",
                "content": [
                    ["Показатель", "Q2 2024", "Q3 2024", "Изменение"],
                    ["Выручка", "1 500 000", "1 800 000", "+20%"],
                    ["Чистая прибыль", "300 000", "360 000", "+20%"],
                    ["Количество клиентов", "1 250", "1 450", "+16%"]
                ],
                "metadata": {
                    "header_row": True,
                    "col_widths": [200, 100, 100, 100]
                }
            },
            {
                "type": "text",
                "content": "Основные достижения квартала:\n\n• Запущен новый продукт\n• Расширена команда разработки\n• Заключены ключевые партнерства",
                "style": {
                    "base_style": "Normal",
                    "space_before": 20
                }
            },
            {
                "type": "image",
                "content": "https://via.placeholder.com/600x400",  # Тестовое изображение
                "metadata": {
                    "caption": "График роста выручки",
                    "max_width": 400,
                    "max_height": 300
                }
            }
        ]
    }
    
    # Создаем генератор PDF
    pdf_generator = PDFGenerator()
    
    # Генерируем PDF из JSON
    success = pdf_generator.generate_from_json(
        json_structure=example_json,
        output_path="quarterly_report.pdf"
    )
    
    if success:
        print("PDF отчет успешно создан!")
    else:
        print("Ошибка при создании PDF отчета")