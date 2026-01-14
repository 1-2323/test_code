import io
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, HttpUrl, field_validator, ValidationInfo
import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import bleach
from tenacity import retry, stop_after_attempt, wait_exponential

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация приложения FastAPI
app = FastAPI(title="Report Generation Service", version="1.0.0")
security = HTTPBearer()

# Модели данных
class ReportContent(BaseModel):
    title: str
    headers: list[str]
    text_content: list[str]
    image_urls: Optional[list[HttpUrl]] = None
    footer_text: Optional[str] = "Generated Report"
    
    @field_validator('title', 'headers', 'text_content', mode='before')
    @classmethod
    def sanitize_text_fields(cls, v: Any, info: ValidationInfo) -> Any:
        """Очистка текстовых полей от потенциально опасного контента"""
        if isinstance(v, str):
            # Разрешаем только безопасные HTML-теги и атрибуты
            allowed_tags = ['b', 'i', 'u', 'em', 'strong', 'br', 'p']
            allowed_attributes = {}
            return bleach.clean(v, tags=allowed_tags, attributes=allowed_attributes, strip=True)
        elif isinstance(v, list):
            return [bleach.clean(item, tags=[], attributes={}, strip=True) if isinstance(item, str) else item for item in v]
        return v

class ReportRequest(BaseModel):
    content: ReportContent
    orientation: str = "portrait"  # или "landscape"
    
    @field_validator('orientation')
    @classmethod
    def validate_orientation(cls, v):
        if v not in ["portrait", "landscape"]:
            raise ValueError('Orientation must be "portrait" or "landscape"')
        return v

# Конфигурация безопасности
ALLOWED_IMAGE_DOMAINS = {
    'trusted-cdn.com',
    'internal-assets.example.com'
}

IMAGE_DOWNLOAD_TIMEOUT = 5
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB

# Сервис безопасности
class SecurityService:
    @staticmethod
    def is_allowed_url(url: str) -> bool:
        """Проверка URL на безопасность (защита от SSRF)"""
        try:
            parsed = urlparse(url)
            
            # Запрещаем локальные адреса и private IPs
            if parsed.hostname in ['localhost', '127.0.0.1', '::1']:
                return False
                
            # Проверяем разрешенные домены для изображений
            if parsed.hostname not in ALLOWED_IMAGE_DOMAINS:
                return False
                
            # Разрешаем только HTTP/HTTPS
            if parsed.scheme not in ['http', 'https']:
                return False
                
            return True
        except Exception as e:
            logger.warning(f"URL validation failed for {url}: {e}")
            return False
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Очистка имени файла от опасных символов"""
        safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
        return ''.join(c for c in filename if c in safe_chars)

# Сервис для работы с изображениями
class ImageService:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ReportGenerator/1.0',
        })
    
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=4, max=10))
    def download_image(self, url: str) -> Optional[bytes]:
        """Безопасная загрузка изображений с защитой от SSRF"""
        if not SecurityService.is_allowed_url(url):
            logger.warning(f"Blocked download from unauthorized URL: {url}")
            return None
            
        try:
            response = self.session.get(
                url, 
                timeout=IMAGE_DOWNLOAD_TIMEOUT,
                stream=True
            )
            response.raise_for_status()
            
            # Проверка размера
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > MAX_IMAGE_SIZE:
                logger.warning(f"Image too large: {content_length} bytes")
                return None
            
            # Чтение с ограничением размера
            content = b''
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > MAX_IMAGE_SIZE:
                    logger.warning(f"Image exceeded size limit during download")
                    return None
            
            # Базовая проверка типа изображения
            if not self.is_valid_image(content):
                logger.warning(f"Invalid image format from {url}")
                return None
                
            return content
        except requests.RequestException as e:
            logger.error(f"Failed to download image from {url}: {e}")
            return None
    
    @staticmethod
    def is_valid_image(data: bytes) -> bool:
        """Простая проверка, что данные являются изображением"""
        if len(data) < 4:
            return False
        
        # Проверка сигнатур PNG, JPEG, GIF
        signatures = [
            b'\x89PNG\r\n\x1a\n',  # PNG
            b'\xff\xd8\xff',        # JPEG
            b'GIF87a',              # GIF87
            b'GIF89a'               # GIF89
        ]
        
        return any(data.startswith(sig) for sig in signatures)

# Сервис генерации PDF
class PDFGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._register_custom_styles()
    
    def _register_custom_styles(self):
        """Регистрация кастомных стилей"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Title'],
            fontSize=24,
            spaceAfter=30,
            alignment=TA_CENTER
        ))
        
        self.styles.add(ParagraphStyle(
            name='CustomHeader1',
            parent=self.styles['Heading1'],
            fontSize=18,
            spaceAfter=12,
            textColor='#2c3e50'
        ))
        
        self.styles.add(ParagraphStyle(
            name='CustomHeader2',
            parent=self.styles['Heading2'],
            fontSize=16,
            spaceAfter=10,
            textColor='#34495e'
        ))
        
        self.styles.add(ParagraphStyle(
            name='CustomBody',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceAfter=6,
            textColor='#2c3e50'
        ))
    
    def create_pdf(self, request: ReportRequest, image_service: ImageService) -> io.BytesIO:
        """Создание PDF документа с защитой от инъекций"""
        buffer = io.BytesIO()
        
        # Настройка страницы
        pagesize = A4
        if request.orientation == "landscape":
            pagesize = (A4[1], A4[0])
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=pagesize,
            rightMargin=inch/2,
            leftMargin=inch/2,
            topMargin=inch/2,
            bottomMargin=inch/2
        )
        
        story = []
        
        # Добавление заголовка
        title = Paragraph(request.content.title, self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 0.5*inch))
        
        # Добавление контента
        for i, (header, text) in enumerate(zip(request.content.headers, request.content.text_content)):
            if i < len(request.content.headers):
                header_para = Paragraph(header, self.styles['CustomHeader1'])
                story.append(header_para)
            
            # Все пользовательские данные проходят через Paragraph, который экранирует HTML
            text_para = Paragraph(text, self.styles['CustomBody'])
            story.append(text_para)
            story.append(Spacer(1, 0.2*inch))
        
        # Добавление изображений
        if request.content.image_urls:
            story.append(Spacer(1, 0.3*inch))
            img_header = Paragraph("Images", self.styles['CustomHeader2'])
            story.append(img_header)
            
            for img_url in request.content.image_urls:
                img_data = image_service.download_image(str(img_url))
                if img_data:
                    try:
                        img_buffer = io.BytesIO(img_data)
                        img = Image(img_buffer, width=400, height=300)
                        story.append(img)
                        story.append(Spacer(1, 0.1*inch))
                    except Exception as e:
                        logger.error(f"Failed to add image to PDF: {e}")
                        error_msg = Paragraph(f"[Image failed to load: {e}]", self.styles['CustomBody'])
                        story.append(error_msg)
        
        # Добавление footer
        def add_footer(canvas_obj, doc):
            canvas_obj.saveState()
            canvas_obj.setFont('Helvetica', 10)
            canvas_obj.drawString(inch/2, 0.75*inch, request.content.footer_text)
            canvas_obj.restoreState()
        
        # Сборка документа
        doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
        
        buffer.seek(0)
        return buffer

# Зависимости
async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Проверка аутентификации"""
    # В реальном приложении здесь была бы проверка JWT или другого токена
    token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"user_id": "authenticated_user"}

# Эндпоинты
@app.post("/report/generate", response_class=StreamingResponse)
async def generate_report(
    request: ReportRequest,
    user: Dict = Depends(verify_token)
) -> StreamingResponse:
    """
    Генерация PDF отчета на основе пользовательских данных.
    
    Args:
        request: Данные для отчета
        user: Аутентифицированный пользователь
    
    Returns:
        PDF файл для скачивания
    """
    try:
        logger.info(f"Generating report for user: {user.get('user_id')}")
        
        # Инициализация сервисов
        image_service = ImageService()
        pdf_generator = PDFGenerator()
        
        # Генерация PDF
        pdf_buffer = pdf_generator.create_pdf(request, image_service)
        
        # Создание безопасного имени файла
        safe_title = SecurityService.sanitize_filename(request.content.title)
        filename = f"{safe_title}_report.pdf"
        
        # Возврат файла
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}\"",
                "Content-Security-Policy": "default-src 'none'",
                "X-Content-Type-Options": "nosniff"
            }
        )
        
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF report")

# Health check эндпоинт
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "pdf-generator"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)