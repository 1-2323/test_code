from flask import Flask, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import uuid
import hashlib
import tempfile
import logging
from functools import wraps
from reportlab.lib.pagesizes import A4, letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.lib import colors
from reportlab.lib.units import inch, cm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import requests
from PIL import Image as PILImage
import io
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///reports.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB максимальный размер
app.config['REPORT_STORAGE_PATH'] = os.environ.get('REPORT_STORAGE_PATH', './reports')
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg'}
app.config['MAX_IMAGE_SIZE_MB'] = 5
app.config['REPORT_TTL_DAYS'] = int(os.environ.get('REPORT_TTL_DAYS', 7))

# Создание директории для хранения отчетов
os.makedirs(app.config['REPORT_STORAGE_PATH'], exist_ok=True)

db = SQLAlchemy(app)

# Модель для хранения сгенерированных отчетов
class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)  # ID пользователя из системы аутентификации
    title = db.Column(db.String(500), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    filepath = db.Column(db.String(1000), nullable=False)
    file_hash = db.Column(db.String(64), unique=True, nullable=False)  # SHA-256 хеш файла
    file_size = db.Column(db.Integer, nullable=False)  # Размер в байтах
    status = db.Column(db.String(50), default='processing')  # processing, completed, failed
    pages = db.Column(db.Integer, default=0)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    download_count = db.Column(db.Integer, default=0)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    
    # Параметры отчета
    page_size = db.Column(db.String(50), default='A4')  # A4, letter, A3, etc.
    orientation = db.Column(db.String(20), default='portrait')  # portrait, landscape
    include_header = db.Column(db.Boolean, default=True)
    include_footer = db.Column(db.Boolean, default=True)
    watermark = db.Column(db.String(200))

# Модель для шаблонов отчетов
class ReportTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    header_template = db.Column(db.Text)
    footer_template = db.Column(db.Text)
    styles = db.Column(db.Text)  # JSON с настройками стилей
    default_page_size = db.Column(db.String(50), default='A4')
    default_orientation = db.Column(db.String(20), default='portrait')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def authenticate_user(f):
    """
    Декоратор для аутентификации пользователя
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # В реальном приложении здесь должна быть проверка токена
        # token = request.headers.get('Authorization')
        # user = verify_token(token)
        
        # Для примера используем заглушку
        user_id = 1  # Извлеченный из токена ID пользователя
        
        return f(user_id, *args, **kwargs)
    return decorated_function

def validate_image_url(url):
    """
    Проверка и загрузка изображения по URL
    """
    try:
        response = requests.get(url, timeout=10, stream=True)
        if response.status_code == 200:
            # Проверка типа контента
            content_type = response.headers.get('content-type', '')
            if 'image' not in content_type:
                return None, 'URL does not point to an image'
            
            # Проверка размера
            content_length = int(response.headers.get('content-length', 0))
            if content_length > app.config['MAX_IMAGE_SIZE_MB'] * 1024 * 1024:
                return None, f'Image size exceeds {app.config["MAX_IMAGE_SIZE_MB"]}MB limit'
            
            # Загружаем изображение
            image_data = io.BytesIO()
            for chunk in response.iter_content(chunk_size=8192):
                image_data.write(chunk)
            
            image_data.seek(0)
            
            # Проверяем, что это валидное изображение
            try:
                img = PILImage.open(image_data)
                img.verify()  # Проверяем целостность файла
                image_data.seek(0)
                return image_data, None
            except:
                return None, 'Invalid image file'
        else:
            return None, f'Failed to download image: HTTP {response.status_code}'
    except requests.exceptions.RequestException as e:
        return None, f'Error downloading image: {str(e)}'

class PDFGenerator:
    """
    Класс для генерации PDF отчетов
    """
    def __init__(self, template_name='default'):
        self.template = ReportTemplate.query.filter_by(name=template_name, is_active=True).first()
        if not self.template:
            self.template = ReportTemplate(
                name='default',
                header_template='',
                footer_template='',
                styles='{}',
                default_page_size='A4',
                default_orientation='portrait'
            )
        
        self.styles = self._load_styles()
    
    def _load_styles(self):
        """
        Загрузка стилей из шаблона
        """
        try:
            template_styles = json.loads(self.template.styles) if self.template.styles else {}
        except:
            template_styles = {}
        
        styles = getSampleStyleSheet()
        
        # Кастомные стили
        if 'title' in template_styles:
            styles.add(ParagraphStyle(
                'CustomTitle',
                parent=styles['Title'],
                **template_styles['title']
            ))
        else:
            styles.add(ParagraphStyle(
                'CustomTitle',
                parent=styles['Title'],
                fontSize=24,
                spaceAfter=30,
                alignment=TA_CENTER
            ))
        
        if 'heading1' in template_styles:
            styles.add(ParagraphStyle(
                'CustomHeading1',
                parent=styles['Heading1'],
                **template_styles['heading1']
            ))
        else:
            styles.add(ParagraphStyle(
                'CustomHeading1',
                parent=styles['Heading1'],
                fontSize=18,
                spaceAfter=12,
                textColor=colors.HexColor('#2c3e50')
            ))
        
        if 'heading2' in template_styles:
            styles.add(ParagraphStyle(
                'CustomHeading2',
                parent=styles['Heading2'],
                **template_styles['heading2']
            ))
        else:
            styles.add(ParagraphStyle(
                'CustomHeading2',
                parent=styles['Heading2'],
                fontSize=14,
                spaceAfter=10,
                textColor=colors.HexColor('#34495e')
            ))
        
        if 'normal' in template_styles:
            styles.add(ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                **template_styles['normal']
            ))
        else:
            styles.add(ParagraphStyle(
                'CustomNormal',
                parent=styles['Normal'],
                fontSize=11,
                spaceAfter=6,
                leading=14
            ))
        
        if 'footer' in template_styles:
            styles.add(ParagraphStyle(
                'CustomFooter',
                parent=styles['Normal'],
                **template_styles['footer']
            ))
        else:
            styles.add(ParagraphStyle(
                'CustomFooter',
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.gray,
                alignment=TA_CENTER
            ))
        
        return styles
    
    def _get_page_size(self, page_size_str, orientation):
        """
        Получение размера страницы
        """
        page_sizes = {
            'A4': A4,
            'A3': (29.7*cm, 42.0*cm),
            'letter': letter,
            'legal': (8.5*inch, 14*inch)
        }
        
        size = page_sizes.get(page_size_str, A4)
        if orientation == 'landscape':
            size = landscape(size)
        
        return size
    
    def generate(self, data, output_path, page_size='A4', orientation='portrait', 
                 include_header=True, include_footer=True, watermark=None):
        """
        Генерация PDF файла
        """
        # Настройка документа
        page_size_obj = self._get_page_size(page_size, orientation)
        doc = SimpleDocTemplate(
            output_path,
            pagesize=page_size_obj,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )
        
        story = []
        
        # Заголовок
        if 'title' in data and data['title']:
            story.append(Paragraph(data['title'], self.styles['CustomTitle']))
            story.append(Spacer(1, 20))
        
        # Генерация содержимого
        if 'sections' in data:
            for section in data['sections']:
                if 'heading' in section and section['heading']:
                    story.append(Paragraph(section['heading'], self.styles['CustomHeading1']))
                    story.append(Spacer(1, 10))
                
                if 'content' in section and section['content']:
                    story.append(Paragraph(section['content'], self.styles['CustomNormal']))
                    story.append(Spacer(1, 15))
                
                if 'subsections' in section:
                    for subsection in section['subsections']:
                        if 'heading' in subsection and subsection['heading']:
                            story.append(Paragraph(subsection['heading'], self.styles['CustomHeading2']))
                            story.append(Spacer(1, 5))
                        
                        if 'content' in subsection and subsection['content']:
                            story.append(Paragraph(subsection['content'], self.styles['CustomNormal']))
                            story.append(Spacer(1, 10))
                
                if 'images' in section and section['images']:
                    for img_data in section['images']:
                        if 'url' in img_data:
                            img_file, error = validate_image_url(img_data['url'])
                            if img_file:
                                try:
                                    img = Image(img_file)
                                    img.drawHeight = min(img.drawHeight, 400)  # Ограничение высоты
                                    img.drawWidth = min(img.drawWidth, 500)   # Ограничение ширины
                                    story.append(img)
                                    story.append(Spacer(1, 10))
                                except:
                                    logger.error(f"Failed to add image: {img_data['url']}")
                
                if 'tables' in section and section['tables']:
                    for table_data in section['tables']:
                        if 'data' in table_data and table_data['data']:
                            table = Table(table_data['data'])
                            table.setStyle(TableStyle([
                                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                ('FONTSIZE', (0, 0), (-1, 0), 10),
                                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                                ('GRID', (0, 0), (-1, -1), 1, colors.black)
                            ]))
                            story.append(table)
                            story.append(Spacer(1, 20))
                
                if 'page_break' in section and section.get('page_break', False):
                    story.append(PageBreak())
        
        # Построение документа
        def add_header_footer(canvas, doc):
            """
            Добавление header и footer
            """
            canvas.saveState()
            
            # Header
            if include_header and self.template.header_template:
                canvas.setFont('Helvetica', 9)
                canvas.drawString(doc.leftMargin, doc.height + doc.topMargin - 20, 
                                self.template.header_template)
            
            # Footer
            if include_footer:
                footer_text = f"Страница {canvas.getPageNumber()} | {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                if self.template.footer_template:
                    footer_text = self.template.footer_template.replace('{page}', str(canvas.getPageNumber())) \
                                                               .replace('{date}', datetime.now().strftime('%d.%m.%Y')) \
                                                               .replace('{time}', datetime.now().strftime('%H:%M'))
                
                canvas.setFont('Helvetica', 8)
                canvas.drawCentredString(doc.width / 2.0, doc.bottomMargin - 20, footer_text)
            
            # Watermark
            if watermark:
                canvas.saveState()
                canvas.setFont('Helvetica', 60)
                canvas.setFillAlpha(0.1)
                canvas.translate(doc.width / 2, doc.height / 2)
                canvas.rotate(45)
                canvas.drawCentredString(0, 0, watermark)
                canvas.restoreState()
            
            canvas.restoreState()
        
        doc.build(story, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
        
        return doc

@app.route('/report/generate', methods=['POST'])
@authenticate_user
def generate_report(user_id):
    """
    Эндпоинт для генерации PDF отчета
    """
    try:
        data = request.get_json()
        
        # Валидация входных данных
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        # Обязательные поля
        if 'title' not in data or not data['title']:
            return jsonify({
                'success': False,
                'error': 'Report title is required'
            }), 400
        
        if 'sections' not in data or not isinstance(data['sections'], list):
            return jsonify({
                'success': False,
                'error': 'Report sections are required and must be an array'
            }), 400
        
        # Генерация уникального ID отчета
        report_id = str(uuid.uuid4())
        
        # Параметры отчета
        template_name = data.get('template', 'default')
        page_size = data.get('page_size', 'A4')
        orientation = data.get('orientation', 'portrait')
        include_header = data.get('include_header', True)
        include_footer = data.get('include_footer', True)
        watermark = data.get('watermark')
        
        # Создание записи в базе
        filename = f"report_{report_id}.pdf"
        filepath = os.path.join(app.config['REPORT_STORAGE_PATH'], filename)
        
        report = Report(
            report_id=report_id,
            user_id=user_id,
            title=data['title'],
            filename=filename,
            filepath=filepath,
            file_hash='',  # Заполнится после генерации
            file_size=0,
            status='processing',
            page_size=page_size,
            orientation=orientation,
            include_header=include_header,
            include_footer=include_footer,
            watermark=watermark,
            expires_at=datetime.utcnow() + timedelta(days=app.config['REPORT_TTL_DAYS']),
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        
        db.session.add(report)
        db.session.commit()
        
        try:
            # Генерация PDF
            generator = PDFGenerator(template_name)
            doc = generator.generate(
                data,
                filepath,
                page_size=page_size,
                orientation=orientation,
                include_header=include_header,
                include_footer=include_footer,
                watermark=watermark
            )
            
            # Вычисление хеша файла и размера
            with open(filepath, 'rb') as f:
                file_content = f.read()
                file_hash = hashlib.sha256(file_content).hexdigest()
                file_size = len(file_content)
            
            # Обновление записи в базе
            report.status = 'completed'
            report.file_hash = file_hash
            report.file_size = file_size
            report.pages = len(doc._calcPageNums([]))
            
            # Проверка на дубликаты (если такой отчет уже был сгенерирован)
            existing_report = Report.query.filter_by(
                file_hash=file_hash,
                user_id=user_id
            ).first()
            
            if existing_report and existing_report.id != report.id:
                # Удаляем только что созданный файл, т.к. он дубликат
                try:
                    os.remove(filepath)
                except:
                    pass
                
                # Обновляем путь к существующему файлу
                report.filepath = existing_report.filepath
                report.filename = existing_report.filename
                report.download_count = existing_report.download_count
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'report_id': report_id,
                'filename': report.filename,
                'download_url': f'/report/download/{report_id}',
                'file_size': file_size,
                'pages': report.pages,
                'generated_at': report.generated_at.isoformat(),
                'expires_at': report.expires_at.isoformat()
            }), 201
            
        except Exception as e:
            logger.error(f"PDF generation error: {str(e)}")
            
            report.status = 'failed'
            db.session.commit()
            
            # Удаляем частично созданный файл
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
            
            return jsonify({
                'success': False,
                'error': 'Failed to generate PDF report',
                'report_id': report_id
            }), 500
            
    except Exception as e:
        logger.error(f"Error in generate_report: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/report/download/<report_id>', methods=['GET'])
@authenticate_user
def download_report(user_id, report_id):
    """
    Эндпоинт для скачивания сгенерированного отчета
    """
    try:
        # Поиск отчета
        report = Report.query.filter_by(report_id=report_id, user_id=user_id).first()
        
        if not report:
            return jsonify({
                'success': False,
                'error': 'Report not found'
            }), 404
        
        if report.status != 'completed':
            return jsonify({
                'success': False,
                'error': f'Report is not ready. Status: {report.status}'
            }), 400
        
        if report.expires_at and report.expires_at < datetime.utcnow():
            return jsonify({
                'success': False,
                'error': 'Report has expired'
            }), 410
        
        # Проверка существования файла
        if not os.path.exists(report.filepath):
            return jsonify({
                'success': False,
                'error': 'Report file not found'
            }), 404
        
        # Обновляем счетчик скачиваний
        report.download_count += 1
        db.session.commit()
        
        # Отправка файла
        return send_file(
            report.filepath,
            as_attachment=True,
            download_name=report.filename,
            mimetype='application/pdf'
        )
        
    except Exception as e:
        logger.error(f"Error in download_report: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/report/status/<report_id>', methods=['GET'])
@authenticate_user
def get_report_status(user_id, report_id):
    """
    Получение статуса отчета
    """
    try:
        report = Report.query.filter_by(report_id=report_id, user_id=user_id).first()
        
        if not report:
            return jsonify({
                'success': False,
                'error': 'Report not found'
            }), 404
        
        response_data = {
            'report_id': report.report_id,
            'title': report.title,
            'status': report.status,
            'generated_at': report.generated_at.isoformat(),
            'expires_at': report.expires_at.isoformat() if report.expires_at else None,
            'download_count': report.download_count,
            'file_size': report.file_size,
            'pages': report.pages,
            'download_url': f'/report/download/{report_id}' if report.status == 'completed' else None
        }
        
        return jsonify({
            'success': True,
            'report': response_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error in get_report_status: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/report/list', methods=['GET'])
@authenticate_user
def list_reports(user_id):
    """
    Получение списка отчетов пользователя
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        # Запрос отчетов пользователя
        reports_query = Report.query.filter_by(user_id=user_id).order_by(Report.generated_at.desc())
        
        pagination = reports_query.paginate(page=page, per_page=per_page, error_out=False)
        
        reports_list = []
        for report in pagination.items:
            reports_list.append({
                'report_id': report.report_id,
                'title': report.title,
                'status': report.status,
                'generated_at': report.generated_at.isoformat(),
                'file_size': report.file_size,
                'pages': report.pages,
                'download_count': report.download_count,
                'expires_at': report.expires_at.isoformat() if report.expires_at else None
            })
        
        return jsonify({
            'success': True,
            'reports': reports_list,
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error in list_reports: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Эндпоинт для очистки устаревших отчетов
@app.route('/admin/reports/cleanup', methods=['POST'])
def cleanup_reports():
    """
    Очистка устаревших отчетов (административный эндпоинт)
    """
    try:
        # В реальном приложении здесь должна быть проверка прав администратора
        
        expired_reports = Report.query.filter(
            Report.expires_at < datetime.utcnow()
        ).all()
        
        deleted_count = 0
        for report in expired_reports:
            # Удаление файла
            try:
                if os.path.exists(report.filepath):
                    os.remove(report.filepath)
            except:
                pass
            
            # Удаление записи из базы
            db.session.delete(report)
            deleted_count += 1
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Cleaned up {deleted_count} expired reports'
        }), 200
        
    except Exception as e:
        logger.error(f"Error in cleanup_reports: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Инициализация базы данных
def init_db():
    with app.app_context():
        db.create_all()
        # Создаем дефолтный шаблон если база пуста
        if not ReportTemplate.query.first():
            default_template = ReportTemplate(
                name='default',
                description='Default report template',
                header_template='Отчет',
                footer_template='Страница {page} | {date}',
                styles=json.dumps({
                    'title': {
                        'fontSize': 24,
                        'spaceAfter': 30,
                        'alignment': TA_CENTER
                    },
                    'heading1': {
                        'fontSize': 18,
                        'spaceAfter': 12,
                        'textColor': '#2c3e50'
                    }
                }),
                default_page_size='A4',
                default_orientation='portrait'
            )
            db.session.add(default_template)
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5000)