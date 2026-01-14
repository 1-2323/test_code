from flask import Flask, request, jsonify, send_file, safe_join, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import uuid
import hashlib
import logging
import mimetypes
import magic
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List, BinaryIO
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading
import json
import zipfile
import tarfile
import shutil
from pathlib import Path
import PIL.Image
from PIL import Image as PILImage
import io
import tempfile

# Инициализация Flask приложения
app = Flask(__name__)

# Конфигурация приложения
app.config.update(
    # Настройки загрузки файлов
    UPLOAD_FOLDER=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'),
    MAX_CONTENT_LENGTH=1024 * 1024 * 100,  # 100MB максимальный размер файла
    ALLOWED_EXTENSIONS={
        'images': {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg', 'ico'},
        'documents': {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf', 'csv'},
        'archives': {'zip', 'tar', 'gz', 'bz2', '7z', 'rar'},
        'media': {'mp3', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv', 'webm'},
        'code': {'py', 'js', 'html', 'css', 'json', 'xml', 'yaml', 'yml'}
    },
    MAX_FILENAME_LENGTH=255,
    
    # Безопасность
    SECRET_KEY='your-secret-key-here-change-in-production',
    REQUIRE_API_KEY=True,
    API_KEYS={'default': generate_password_hash('your-api-key-here')},
    
    # Хранилище
    STORAGE_BACKEND='local',  # local, s3, azure, gcs
    STORAGE_PATH='uploads',
    ENABLE_VIRUS_SCAN=False,  # Требует ClamAV
    
    # Водяные знаки
    ENABLE_WATERMARK=False,
    WATERMARK_TEXT='CONFIDENTIAL',
    WATERMARK_OPACITY=0.3,
    
    # Сжатие
    ENABLE_COMPRESSION=True,
    COMPRESS_IMAGES=True,
    IMAGE_QUALITY=85,
    MAX_IMAGE_DIMENSION=1920,
    
    # Лимиты
    MAX_FILES_PER_REQUEST=10,
    MAX_USER_STORAGE_MB=1024,  # 1GB на пользователя
    FILE_TTL_HOURS=24 * 7,  # 7 дней по умолчанию
    
    # База данных (упрощенная, в реальном проекте используйте SQLAlchemy)
    DATABASE_PATH='uploads.db',
    
    # Логирование
    LOG_LEVEL='INFO',
    LOG_FILE='uploads.log'
)

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, app.config['LOG_LEVEL']),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(app.config['LOG_FILE']),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Создание директорий
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
for subdir in ['temp', 'processed', 'trash', 'thumbnails']:
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], subdir), exist_ok=True)

# Блокировки для потокобезопасности
_file_locks: Dict[str, threading.Lock] = {}
_global_lock = threading.Lock()


class FileStatus(Enum):
    """Статусы файлов"""
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    DELETED = "deleted"
    EXPIRED = "expired"


class StorageType(Enum):
    """Типы хранилищ"""
    LOCAL = "local"
    S3 = "s3"
    AZURE = "azure"
    GCS = "gcs"


@dataclass
class FileMetadata:
    """Метаданные файла"""
    file_id: str
    original_filename: str
    stored_filename: str
    file_size: int
    mime_type: str
    extension: str
    md5_hash: str
    sha256_hash: str
    upload_date: datetime
    expiration_date: Optional[datetime] = None
    status: FileStatus = FileStatus.UPLOADING
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    description: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None  # для видео/аудио
    processed_versions: Dict[str, str] = field(default_factory=dict)  # миниатюры, сжатые версии
    custom_metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_image(self) -> bool:
        return self.mime_type.startswith('image/')
    
    @property
    def is_video(self) -> bool:
        return self.mime_type.startswith('video/')
    
    @property
    def is_audio(self) -> bool:
        return self.mime_type.startswith('audio/')
    
    @property
    def is_expired(self) -> bool:
        if not self.expiration_date:
            return False
        return datetime.now() > self.expiration_date


class FileManager:
    """Менеджер управления файлами"""
    
    def __init__(self):
        self._metadata_store: Dict[str, FileMetadata] = {}
        self._user_quota: Dict[str, int] = {}  # user_id -> использованное пространство в байтах
        self._load_from_disk()
    
    def _load_from_disk(self):
        """Загрузка метаданных с диска"""
        try:
            metadata_file = os.path.join(app.config['UPLOAD_FOLDER'], 'metadata.json')
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                    for file_id, meta_data in data.get('files', {}).items():
                        # Конвертация строк даты обратно в datetime
                        meta_data['upload_date'] = datetime.fromisoformat(meta_data['upload_date'])
                        if meta_data.get('expiration_date'):
                            meta_data['expiration_date'] = datetime.fromisoformat(meta_data['expiration_date'])
                        meta_data['status'] = FileStatus(meta_data['status'])
                        self._metadata_store[file_id] = FileMetadata(**meta_data)
                    
                    self._user_quota = data.get('user_quota', {})
        except Exception as e:
            logger.error(f"Failed to load metadata from disk: {str(e)}")
    
    def _save_to_disk(self):
        """Сохранение метаданных на диск"""
        try:
            metadata_file = os.path.join(app.config['UPLOAD_FOLDER'], 'metadata.json')
            data = {
                'files': {},
                'user_quota': self._user_quota
            }
            
            for file_id, metadata in self._metadata_store.items():
                meta_dict = asdict(metadata)
                # Конвертация datetime в строки
                meta_dict['upload_date'] = metadata.upload_date.isoformat()
                if metadata.expiration_date:
                    meta_dict['expiration_date'] = metadata.expiration_date.isoformat()
                meta_dict['status'] = metadata.status.value
                data['files'][file_id] = meta_dict
            
            with open(metadata_file, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save metadata to disk: {str(e)}")
    
    def generate_file_id(self) -> str:
        """Генерация уникального ID файла"""
        return str(uuid.uuid4())
    
    def get_allowed_extensions(self, file_type: Optional[str] = None) -> set:
        """Получение разрешенных расширений"""
        if file_type:
            return app.config['ALLOWED_EXTENSIONS'].get(file_type, set())
        
        all_extensions = set()
        for extensions in app.config['ALLOWED_EXTENSIONS'].values():
            all_extensions.update(extensions)
        return all_extensions
    
    def is_allowed_file(self, filename: str, file_type: Optional[str] = None) -> bool:
        """Проверка разрешен ли файл"""
        if not filename or '.' not in filename:
            return False
        
        ext = filename.rsplit('.', 1)[1].lower()
        
        if file_type:
            return ext in self.get_allowed_extensions(file_type)
        
        return ext in self.get_allowed_extensions()
    
    def secure_filename(self, filename: str) -> str:
        """Безопасное имя файла с сохранением расширения"""
        # Базовое обеззараживание
        filename = secure_filename(filename)
        
        # Ограничение длины имени
        if len(filename) > app.config['MAX_FILENAME_LENGTH']:
            name, ext = os.path.splitext(filename)
            filename = name[:app.config['MAX_FILENAME_LENGTH'] - len(ext)] + ext
        
        return filename
    
    def detect_mime_type(self, file_path: str, original_filename: str) -> str:
        """Определение MIME типа файла"""
        try:
            # Используем библиотеку magic для точного определения
            mime = magic.Magic(mime=True)
            detected = mime.from_file(file_path)
            
            # Дополнительная проверка для распространенных типов
            if detected == 'application/octet-stream':
                # Попробуем определить по расширению
                ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
                mime_type, _ = mimetypes.guess_type(f"file.{ext}")
                if mime_type:
                    return mime_type
            
            return detected
        except Exception:
            # Fallback на расширение файла
            ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
            mime_type, _ = mimetypes.guess_type(f"file.{ext}")
            return mime_type or 'application/octet-stream'
    
    def calculate_hashes(self, file_path: str) -> Tuple[str, str]:
        """Расчет MD5 и SHA256 хешей файла"""
        md5_hash = hashlib.md5()
        sha256_hash = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                md5_hash.update(chunk)
                sha256_hash.update(chunk)
        
        return md5_hash.hexdigest(), sha256_hash.hexdigest()
    
    def check_user_quota(self, user_id: str, additional_bytes: int = 0) -> bool:
        """Проверка квоты пользователя"""
        if not app.config.get('MAX_USER_STORAGE_MB'):
            return True
        
        max_bytes = app.config['MAX_USER_STORAGE_MB'] * 1024 * 1024
        used_bytes = self._user_quota.get(user_id, 0)
        
        return (used_bytes + additional_bytes) <= max_bytes
    
    def update_user_quota(self, user_id: str, delta_bytes: int):
        """Обновление квоты пользователя"""
        if user_id not in self._user_quota:
            self._user_quota[user_id] = 0
        
        self._user_quota[user_id] += delta_bytes
        
        if self._user_quota[user_id] < 0:
            self._user_quota[user_id] = 0
        
        self._save_to_disk()
    
    def get_file_path(self, metadata: FileMetadata, version: Optional[str] = None) -> str:
        """Получение пути к файлу"""
        if version and version in metadata.processed_versions:
            filename = metadata.processed_versions[version]
        else:
            filename = metadata.stored_filename
        
        return os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    def create_metadata(self, original_filename: str, file_size: int, 
                       user_id: Optional[str] = None,
                       session_id: Optional[str] = None,
                       ttl_hours: Optional[int] = None) -> FileMetadata:
        """Создание метаданных для нового файла"""
        file_id = self.generate_file_id()
        safe_name = self.secure_filename(original_filename)
        
        # Генерация имени для хранения
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        stored_name = f"{timestamp}_{file_id}_{safe_name}"
        
        # Расчет даты истечения
        expiration_date = None
        if ttl_hours:
            expiration_date = datetime.now() + timedelta(hours=ttl_hours)
        elif app.config['FILE_TTL_HOURS']:
            expiration_date = datetime.now() + timedelta(hours=app.config['FILE_TTL_HOURS'])
        
        metadata = FileMetadata(
            file_id=file_id,
            original_filename=original_filename,
            stored_filename=stored_name,
            file_size=file_size,
            mime_type='application/octet-stream',  # Определится позже
            extension=original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else '',
            md5_hash='',
            sha256_hash='',
            upload_date=datetime.now(),
            expiration_date=expiration_date,
            status=FileStatus.UPLOADING,
            user_id=user_id,
            session_id=session_id
        )
        
        return metadata
    
    def save_metadata(self, metadata: FileMetadata):
        """Сохранение метаданных"""
        with _global_lock:
            self._metadata_store[metadata.file_id] = metadata
            self._save_to_disk()
    
    def get_metadata(self, file_id: str) -> Optional[FileMetadata]:
        """Получение метаданных по ID"""
        with _global_lock:
            return self._metadata_store.get(file_id)
    
    def delete_file(self, file_id: str, permanent: bool = False) -> bool:
        """Удаление файла"""
        metadata = self.get_metadata(file_id)
        if not metadata:
            return False
        
        try:
            # Удаление основного файла
            main_path = self.get_file_path(metadata)
            if os.path.exists(main_path):
                if permanent:
                    os.unlink(main_path)
                else:
                    # Перемещение в корзину
                    trash_path = os.path.join(app.config['UPLOAD_FOLDER'], 'trash', metadata.stored_filename)
                    shutil.move(main_path, trash_path)
            
            # Удаление обработанных версий
            for version, filename in metadata.processed_versions.items():
                version_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(version_path):
                    if permanent:
                        os.unlink(version_path)
                    else:
                        trash_path = os.path.join(app.config['UPLOAD_FOLDER'], 'trash', filename)
                        shutil.move(version_path, trash_path)
            
            # Обновление квоты пользователя
            if metadata.user_id:
                self.update_user_quota(metadata.user_id, -metadata.file_size)
            
            # Обновление статуса
            metadata.status = FileStatus.DELETED if permanent else FileStatus.EXPIRED
            self.save_metadata(metadata)
            
            logger.info(f"File {file_id} deleted (permanent: {permanent})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete file {file_id}: {str(e)}")
            return False
    
    def cleanup_expired(self) -> int:
        """Очистка просроченных файлов"""
        count = 0
        now = datetime.now()
        
        with _global_lock:
            for file_id, metadata in list(self._metadata_store.items()):
                if metadata.is_expired and metadata.status != FileStatus.DELETED:
                    if self.delete_file(file_id, permanent=False):
                        count += 1
        
        logger.info(f"Cleaned up {count} expired files")
        return count


class FileProcessor:
    """Процессор для обработки файлов"""
    
    def __init__(self, file_manager: FileManager):
        self.file_manager = file_manager
    
    def process_file(self, metadata: FileMetadata) -> bool:
        """Основная обработка файла"""
        try:
            file_path = self.file_manager.get_file_path(metadata)
            
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return False
            
            # 1. Определение MIME типа
            metadata.mime_type = self.file_manager.detect_mime_type(file_path, metadata.original_filename)
            
            # 2. Расчет хешей
            md5_hash, sha256_hash = self.file_manager.calculate_hashes(file_path)
            metadata.md5_hash = md5_hash
            metadata.sha256_hash = sha256_hash
            
            # 3. Проверка на вирусы (если включено)
            if app.config['ENABLE_VIRUS_SCAN']:
                if not self.scan_for_viruses(file_path):
                    logger.warning(f"Virus scan failed for {metadata.file_id}")
                    metadata.status = FileStatus.FAILED
                    return False
            
            # 4. Обработка в зависимости от типа
            if metadata.is_image:
                self.process_image(metadata, file_path)
            elif metadata.mime_type in ['application/zip', 'application/x-tar', 'application/x-gzip']:
                self.process_archive(metadata, file_path)
            
            # 5. Сжатие изображений (если включено)
            if app.config['ENABLE_COMPRESSION'] and metadata.is_image:
                self.compress_image(metadata)
            
            # 6. Создание миниатюр для изображений
            if metadata.is_image:
                self.create_thumbnail(metadata)
            
            # 7. Добавление водяных знаков (если включено)
            if app.config['ENABLE_WATERMARK'] and metadata.is_image:
                self.add_watermark(metadata)
            
            metadata.status = FileStatus.PROCESSED
            self.file_manager.save_metadata(metadata)
            
            logger.info(f"File {metadata.file_id} processed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to process file {metadata.file_id}: {str(e)}", exc_info=True)
            metadata.status = FileStatus.FAILED
            self.file_manager.save_metadata(metadata)
            return False
    
    def process_image(self, metadata: FileMetadata, file_path: str):
        """Обработка изображений"""
        try:
            with PILImage.open(file_path) as img:
                metadata.width, metadata.height = img.size
                
                # Сохранение EXIF данных
                if hasattr(img, '_getexif') and img._getexif():
                    metadata.custom_metadata['exif'] = dict(img._getexif())
                
                # Конвертация в RGB если необходимо
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = PILImage.new('RGB', img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    
                    # Сохранение обработанной версии
                    processed_name = f"processed_{metadata.stored_filename}"
                    processed_path = os.path.join(app.config['UPLOAD_FOLDER'], processed_name)
                    rgb_img.save(processed_path, 'JPEG', quality=app.config['IMAGE_QUALITY'])
                    
                    metadata.processed_versions['processed'] = processed_name
                    
        except Exception as e:
            logger.error(f"Image processing failed for {metadata.file_id}: {str(e)}")
    
    def process_archive(self, metadata: FileMetadata, file_path: str):
        """Обработка архивов"""
        try:
            extract_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'temp', metadata.file_id)
            os.makedirs(extract_dir, exist_ok=True)
            
            if metadata.mime_type == 'application/zip':
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                    
                    # Сохранение списка файлов в метаданные
                    file_list = zip_ref.namelist()
                    metadata.custom_metadata['archive_contents'] = file_list
                    
            elif metadata.mime_type in ['application/x-tar', 'application/x-gzip']:
                with tarfile.open(file_path, 'r:*') as tar_ref:
                    tar_ref.extractall(extract_dir)
                    
                    file_list = tar_ref.getnames()
                    metadata.custom_metadata['archive_contents'] = file_list
            
            logger.info(f"Archive {metadata.file_id} extracted with {len(file_list)} files")
            
        except Exception as e:
            logger.error(f"Archive processing failed for {metadata.file_id}: {str(e)}")
    
    def compress_image(self, metadata: FileMetadata):
        """Сжатие изображений"""
        try:
            file_path = self.file_manager.get_file_path(metadata)
            
            if metadata.mime_type in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']:
                with PILImage.open(file_path) as img:
                    # Изменение размера если слишком большой
                    if app.config['MAX_IMAGE_DIMENSION']:
                        max_dim = app.config['MAX_IMAGE_DIMENSION']
                        if img.width > max_dim or img.height > max_dim:
                            img.thumbnail((max_dim, max_dim), PILImage.Resampling.LANCZOS)
                    
                    # Сохранение сжатой версии
                    compressed_name = f"compressed_{metadata.stored_filename}"
                    compressed_path = os.path.join(app.config['UPLOAD_FOLDER'], compressed_name)
                    
                    save_kwargs = {'quality': app.config['IMAGE_QUALITY']}
                    if metadata.mime_type == 'image/png':
                        save_kwargs['optimize'] = True
                    
                    img.save(compressed_path, **save_kwargs)
                    
                    metadata.processed_versions['compressed'] = compressed_name
                    
                    # Обновление размера файла
                    compressed_size = os.path.getsize(compressed_path)
                    metadata.custom_metadata['original_size'] = metadata.file_size
                    metadata.custom_metadata['compressed_size'] = compressed_size
                    metadata.custom_metadata['compression_ratio'] = (
                        (metadata.file_size - compressed_size) / metadata.file_size * 100
                    )
                    
                    logger.info(f"Image {metadata.file_id} compressed: {metadata.file_size} -> {compressed_size} bytes")
            
        except Exception as e:
            logger.error(f"Image compression failed for {metadata.file_id}: {str(e)}")
    
    def create_thumbnail(self, metadata: FileMetadata, size: Tuple[int, int] = (200, 200)):
        """Создание миниатюры"""
        try:
            file_path = self.file_manager.get_file_path(metadata)
            
            with PILImage.open(file_path) as img:
                # Создание миниатюры
                img.thumbnail(size, PILImage.Resampling.LANCZOS)
                
                # Сохранение миниатюры
                thumb_name = f"thumbnail_{metadata.stored_filename.rsplit('.', 1)[0]}.jpg"
                thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], 'thumbnails', thumb_name)
                
                # Конвертация в RGB для JPEG
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img.save(thumb_path, 'JPEG', quality=85)
                
                metadata.processed_versions['thumbnail'] = os.path.join('thumbnails', thumb_name)
                
        except Exception as e:
            logger.error(f"Thumbnail creation failed for {metadata.file_id}: {str(e)}")
    
    def add_watermark(self, metadata: FileMetadata):
        """Добавление водяного знака"""
        try:
            file_path = self.file_manager.get_file_path(metadata)
            
            with PILImage.open(file_path).convert('RGBA') as base:
                # Создание слоя для водяного знака
                txt = PILImage.new('RGBA', base.size, (255, 255, 255, 0))
                
                # Создание объекта для рисования
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(txt)
                
                # Попытка загрузить шрифт
                try:
                    font = ImageFont.truetype("arial.ttf", 40)
                except:
                    font = ImageFont.load_default()
                
                # Расчет позиции текста
                text = app.config['WATERMARK_TEXT']
                text_width, text_height = draw.textsize(text, font=font)
                
                # Позиционирование по центру
                position = (
                    (base.width - text_width) // 2,
                    (base.height - text_height) // 2
                )
                
                # Рисование текста
                draw.text(position, text, font=font, 
                         fill=(255, 255, 255, int(255 * app.config['WATERMARK_OPACITY'])))
                
                # Наложение водяного знака
                watermarked = PILImage.alpha_composite(base, txt)
                
                # Сохранение
                watermark_name = f"watermarked_{metadata.stored_filename}"
                watermark_path = os.path.join(app.config['UPLOAD_FOLDER'], watermark_name)
                
                if metadata.mime_type in ['image/jpeg', 'image/jpg']:
                    watermarked = watermarked.convert('RGB')
                
                watermarked.save(watermark_path)
                
                metadata.processed_versions['watermarked'] = watermark_name
                
        except Exception as e:
            logger.error(f"Watermark addition failed for {metadata.file_id}: {str(e)}")
    
    def scan_for_viruses(self, file_path: str) -> bool:
        """Проверка на вирусы (заглушка)"""
        # В реальном проекте интегрируйте ClamAV или другой антивирус
        try:
            import subprocess
            result = subprocess.run(['clamscan', '--quiet', file_path], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        except:
            logger.warning("Virus scanning not available")
            return True


# Инициализация менеджеров
file_manager = FileManager()
file_processor = FileProcessor(file_manager)


def require_api_key(f):
    """Декоратор для проверки API ключа"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not app.config['REQUIRE_API_KEY']:
            return f(*args, **kwargs)
        
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key:
            return jsonify({
                'error': 'API key required',
                'timestamp': datetime.now().isoformat()
            }), 401
        
        # Проверка ключа
        valid = False
        for key_name, key_hash in app.config['API_KEYS'].items():
            if check_password_hash(key_hash, api_key):
                valid = True
                g.api_key_name = key_name
                break
        
        if not valid:
            return jsonify({
                'error': 'Invalid API key',
                'timestamp': datetime.now().isoformat()
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function


def validate_file_request():
    """Валидация запроса на загрузку файла"""
    # Проверка размера
    if request.content_length > app.config['MAX_CONTENT_LENGTH']:
        return False, 'File too large'
    
    # Проверка количества файлов
    if len(request.files) > app.config['MAX_FILES_PER_REQUEST']:
        return False, 'Too many files'
    
    return True, None


@app.route('/upload', methods=['POST'])
@require_api_key
def upload_file():
    """Основной эндпоинт загрузки файлов"""
    start_time = datetime.now()
    
    # Проверка запроса
    is_valid, error_msg = validate_file_request()
    if not is_valid:
        return jsonify({
            'status': 'error',
            'error': error_msg,
            'timestamp': datetime.now().isoformat()
        }), 400
    
    try:
        # Получение параметров
        user_id = request.headers.get('X-User-ID') or request.form.get('user_id')
        session_id = request.headers.get('X-Session-ID') or request.form.get('session_id')
        ttl_hours = request.headers.get('X-File-TTL') or request.form.get('ttl_hours')
        tags = request.form.get('tags', '').split(',')
        description = request.form.get('description')
        
        # Проверка квоты пользователя
        if user_id:
            content_length = request.content_length or 0
            if not file_manager.check_user_quota(user_id, content_length):
                return jsonify({
                    'status': 'error',
                    'error': 'Storage quota exceeded',
                    'timestamp': datetime.now().isoformat()
                }), 403
        
        uploaded_files = []
        errors = []
        
        # Обработка каждого файла
        for file_key in request.files:
            file = request.files[file_key]
            
            if not file or file.filename == '':
                errors.append(f"Empty file for key '{file_key}'")
                continue
            
            # Проверка разрешенных расширений
            if not file_manager.is_allowed_file(file.filename):
                errors.append(f"File type not allowed: {file.filename}")
                continue
            
            # Создание временного файла
            temp_file = tempfile.NamedTemporaryFile(
                delete=False, 
                dir=os.path.join(app.config['UPLOAD_FOLDER'], 'temp')
            )
            
            try:
                # Сохранение файла
                file.save(temp_file.name)
                temp_file.close()
                
                file_size = os.path.getsize(temp_file.name)
                
                # Создание метаданных
                metadata = file_manager.create_metadata(
                    original_filename=file.filename,
                    file_size=file_size,
                    user_id=user_id,
                    session_id=session_id,
                    ttl_hours=int(ttl_hours) if ttl_hours and ttl_hours.isdigit() else None
                )
                
                metadata.tags = [tag.strip() for tag in tags if tag.strip()]
                metadata.description = description
                
                # Перемещение файла в постоянное хранилище
                final_path = file_manager.get_file_path(metadata)
                shutil.move(temp_file.name, final_path)
                
                # Обновление квоты пользователя
                if user_id:
                    file_manager.update_user_quota(user_id, file_size)
                
                # Обработка файла
                file_processor.process_file(metadata)
                
                # Сохранение метаданных
                file_manager.save_metadata(metadata)
                
                uploaded_files.append({
                    'file_id': metadata.file_id,
                    'original_filename': metadata.original_filename,
                    'stored_filename': metadata.stored_filename,
                    'file_size': metadata.file_size,
                    'mime_type': metadata.mime_type,
                    'md5_hash': metadata.md5_hash,
                    'sha256_hash': metadata.sha256_hash,
                    'upload_date': metadata.upload_date.isoformat(),
                    'expiration_date': metadata.expiration_date.isoformat() if metadata.expiration_date else None,
                    'status': metadata.status.value,
                    'processed_versions': metadata.processed_versions,
                    'is_image': metadata.is_image,
                    'is_video': metadata.is_video,
                    'is_audio': metadata.is_audio,
                    'width': metadata.width,
                    'height': metadata.height
                })
                
                logger.info(f"File uploaded: {metadata.original_filename} -> {metadata.file_id}")
                
            except Exception as e:
                errors.append(f"Failed to upload {file.filename}: {str(e)}")
                
                # Очистка временных файлов
                if os.path.exists(temp_file.name):
                    os.unlink(temp_file.name)
        
        # Формирование ответа
        response = {
            'status': 'success' if not errors else 'partial',
            'timestamp': datetime.now().isoformat(),
            'uploaded_files': uploaded_files,
            'total_files': len(uploaded_files),
            'errors': errors,
            'upload_duration': (datetime.now() - start_time).total_seconds()
        }
        
        if errors:
            logger.warning(f"Upload completed with {len(errors)} errors")
        
        return jsonify(response), 200 if not errors else 207
        
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
            'upload_duration': (datetime.now() - start_time).total_seconds()
        }), 500


@app.route('/upload/chunked', methods=['POST'])
@require_api_key
def upload_chunked():
    """Загрузка файлов по частям (chunked upload)"""
    chunk_number = int(request.form.get('chunk_number', 0))
    total_chunks = int(request.form.get('total_chunks', 1))
    file_id = request.form.get('file_id')
    filename = request.form.get('filename')
    
    if not filename:
        return jsonify({
            'status': 'error',
            'error': 'Filename required',
            'timestamp': datetime.now().isoformat()
        }), 400
    
    # Создание или получение метаданных
    if chunk_number == 0:
        # Первый чанк - создаем метаданные
        metadata = file_manager.create_metadata(
            original_filename=filename,
            file_size=0,  # Будет обновлено позже
            user_id=request.headers.get('X-User-ID')
        )
        file_id = metadata.file_id
        
        # Создание временного файла
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp', f"{file_id}.part")
        open(temp_path, 'wb').close()  # Создание пустого файла
        
    else:
        # Последующие чанки - получаем существующие метаданные
        if not file_id:
            return jsonify({
                'status': 'error',
                'error': 'File ID required for subsequent chunks',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        metadata = file_manager.get_metadata(file_id)
        if not metadata:
            return jsonify({
                'status': 'error',
                'error': 'File not found',
                'timestamp': datetime.now().isoformat()
            }), 404
    
    # Сохранение чанка
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp', f"{file_id}.part")
    
    with open(temp_path, 'ab') as f:
        chunk = request.files.get('chunk')
        if chunk:
            f.write(chunk.read())
    
    # Проверка завершения загрузки
    if chunk_number == total_chunks - 1:
        # Загрузка завершена
        file_size = os.path.getsize(temp_path)
        
        # Обновление метаданных
        metadata.file_size = file_size
        metadata.status = FileStatus.UPLOADED
        
        #