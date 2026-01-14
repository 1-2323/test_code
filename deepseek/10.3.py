from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
import io
import os
import uuid
import hashlib
import time
import logging
from datetime import datetime
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor
import mimetypes

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Image Processing API",
    description="API для обработки и изменения размера изображений",
    version="1.0.0"
)

# Модели данных
class ImageResizeRequest(BaseModel):
    """Модель запроса на изменение размера изображения."""
    width: Optional[int] = Field(
        None, 
        ge=1, 
        le=10000, 
        description="Ширина выходного изображения"
    )
    height: Optional[int] = Field(
        None, 
        ge=1, 
        le=10000, 
        description="Высота выходного изображения"
    )
    quality: int = Field(
        85, 
        ge=1, 
        le=100, 
        description="Качество изображения (1-100)"
    )
    keep_aspect_ratio: bool = Field(
        True, 
        description="Сохранять соотношение сторон"
    )
    upscale: bool = Field(
        False, 
        description="Разрешить увеличение изображения"
    )
    background_color: str = Field(
        "white", 
        regex="^#[0-9a-fA-F]{6}$|^[a-zA-Z]+$",
        description="Цвет фона (HEX или название)"
    )
    format: str = Field(
        "auto",
        regex="^(auto|jpeg|png|webp|bmp|gif)$",
        description="Формат выходного изображения"
    )
    crop: bool = Field(
        False,
        description="Обрезать изображение до заданных размеров"
    )
    watermark: Optional[str] = Field(
        None,
        description="Текст водяного знака"
    )

class ImageProcessResponse(BaseModel):
    """Модель ответа после обработки изображения."""
    request_id: str
    original_filename: str
    processed_filename: str
    original_size: Tuple[int, int]
    processed_size: Tuple[int, int]
    file_size: int
    format: str
    processing_time: float
    download_url: str
    expires_at: datetime

class ErrorResponse(BaseModel):
    """Модель ответа об ошибке."""
    error: str
    detail: Optional[str] = None
    request_id: Optional[str] = None

# Конфигурация
class ImageProcessingConfig:
    """Конфигурация обработки изображений."""
    def __init__(self):
        self.UPLOAD_DIR = Path("uploads")
        self.PROCESSED_DIR = Path("processed")
        self.CACHE_DIR = Path("cache")
        self.MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
        self.ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
        self.ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/webp', 'image/tiff'}
        self.MAX_DIMENSION = 10000
        self.FILE_TTL = 3600  # Время жизни файлов в секундах
        self.CACHE_TTL = 300  # Время жизни кэша в секундах
        self.MAX_WORKERS = 4
        
        # Создание директорий
        for directory in [self.UPLOAD_DIR, self.PROCESSED_DIR, self.CACHE_DIR]:
            directory.mkdir(exist_ok=True, parents=True)

config = ImageProcessingConfig()

# Кэш обработки
class ImageCache:
    """Кэш обработанных изображений."""
    def __init__(self):
        self.cache = {}
        
    def get_key(self, file_hash: str, params: dict) -> str:
        """Генерация ключа кэша."""
        param_str = str(sorted(params.items()))
        return hashlib.md5(f"{file_hash}:{param_str}".encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Path]:
        """Получение файла из кэша."""
        if key in self.cache:
            path, timestamp = self.cache[key]
            if time.time() - timestamp < config.CACHE_TTL:
                return path
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, path: Path) -> None:
        """Добавление файла в кэш."""
        self.cache[key] = (path, time.time())

image_cache = ImageCache()

# Валидация
def validate_image_file(file: UploadFile) -> Tuple[bool, Optional[str]]:
    """Валидация загружаемого файла изображения."""
    # Проверка MIME-типа
    if file.content_type not in config.ALLOWED_MIME_TYPES:
        return False, f"Неподдерживаемый MIME-тип: {file.content_type}"
    
    # Проверка расширения
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in config.ALLOWED_EXTENSIONS:
        return False, f"Неподдерживаемое расширение: {file_ext}"
    
    return True, None

def validate_resize_params(width: int, height: int, upscale: bool) -> Tuple[bool, Optional[str]]:
    """Валидация параметров изменения размера."""
    if width > config.MAX_DIMENSION or height > config.MAX_DIMENSION:
        return False, f"Размер не может превышать {config.MAX_DIMENSION}px"
    
    if width * height > 100_000_000:  # 100 мегапикселей
        return False, "Слишком большое разрешение"
    
    if not upscale and (width > 5000 or height > 5000):
        return False, "Увеличение изображения запрещено"
    
    return True, None

# Обработка изображений
class ImageProcessor:
    """Процессор изображений."""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)
    
    async def process_image(
        self,
        image_data: bytes,
        original_filename: str,
        params: ImageResizeRequest
    ) -> Tuple[Image.Image, str]:
        """Асинхронная обработка изображения."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._process_image_sync,
            image_data,
            original_filename,
            params
        )
    
    def _process_image_sync(
        self,
        image_data: bytes,
        original_filename: str,
        params: ImageResizeRequest
    ) -> Tuple[Image.Image, str]:
        """Синхронная обработка изображения."""
        try:
            # Открытие изображения
            image = Image.open(io.BytesIO(image_data))
            
            # Конвертация в RGB если нужно
            if image.mode in ('RGBA', 'LA', 'P'):
                # Создание фона для изображений с прозрачностью
                if params.background_color.startswith('#'):
                    background = Image.new('RGB', image.size, params.background_color)
                else:
                    background = Image.new('RGB', image.size, params.background_color)
                
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Получение оригинальных размеров
            original_width, original_height = image.size
            
            # Расчет целевых размеров
            target_width = params.width or original_width
            target_height = params.height or original_height
            
            # Сохранение соотношения сторон
            if params.keep_aspect_ratio and not params.crop:
                if params.width and params.height:
                    # Подгонка с сохранением соотношения сторон
                    ratio = min(
                        target_width / original_width,
                        target_height / original_height
                    )
                    if not params.upscale and ratio > 1:
                        ratio = 1
                    target_width = int(original_width * ratio)
                    target_height = int(original_height * ratio)
                elif params.width:
                    # Ширина задана, высота рассчитывается
                    ratio = target_width / original_width
                    if not params.upscale and ratio > 1:
                        ratio = 1
                    target_width = int(original_width * ratio)
                    target_height = int(original_height * ratio)
                elif params.height:
                    # Высота задана, ширина рассчитывается
                    ratio = target_height / original_height
                    if not params.upscale and ratio > 1:
                        ratio = 1
                    target_height = int(original_height * ratio)
                    target_width = int(original_width * ratio)
            
            # Обработка обрезки
            if params.crop and params.width and params.height:
                # Центрированная обрезка
                image = ImageOps.fit(
                    image,
                    (target_width, target_height),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5)
                )
            else:
                # Изменение размера
                image = image.resize(
                    (target_width, target_height),
                    resample=Image.Resampling.LANCZOS
                )
            
            # Добавление водяного знака
            if params.watermark:
                image = self._add_watermark(image, params.watermark)
            
            # Определение формата выходного файла
            output_format = params.format
            if output_format == "auto":
                # Определение по оригинальному файлу
                original_ext = Path(original_filename).suffix.lower()
                if original_ext in ['.jpg', '.jpeg']:
                    output_format = "JPEG"
                elif original_ext == '.png':
                    output_format = "PNG"
                elif original_ext == '.webp':
                    output_format = "WEBP"
                elif original_ext == '.gif':
                    output_format = "GIF"
                elif original_ext == '.bmp':
                    output_format = "BMP"
                else:
                    output_format = "JPEG"
            else:
                output_format = output_format.upper()
            
            return image, output_format
            
        except UnidentifiedImageError:
            raise HTTPException(status_code=400, detail="Невозможно прочитать файл изображения")
        except Exception as e:
            logger.error(f"Ошибка обработки изображения: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Ошибка обработки изображения: {str(e)}")
    
    def _add_watermark(self, image: Image.Image, text: str) -> Image.Image:
        """Добавление текстового водяного знака."""
        from PIL import ImageDraw, ImageFont
        import random
        
        # Создание копии изображения для редактирования
        watermark_image = image.copy()
        
        # Создание объекта для рисования
        draw = ImageDraw.Draw(watermark_image)
        
        # Размеры изображения
        width, height = watermark_image.size
        
        # Выбор шрифта и размера
        try:
            font_size = max(width, height) // 20
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            # Fallback на стандартный шрифт
            font = ImageFont.load_default()
        
        # Позиционирование водяного знака (случайное с отступами)
        text_width, text_height = draw.textsize(text, font=font)
        x = random.randint(20, width - text_width - 20)
        y = random.randint(20, height - text_height - 20)
        
        # Рисование водяного знака с тенью
        shadow_color = (0, 0, 0, 128)
        text_color = (255, 255, 255, 180)
        
        # Тень
        draw.text((x+2, y+2), text, font=font, fill=shadow_color)
        # Основной текст
        draw.text((x, y), text, font=font, fill=text_color)
        
        return watermark_image
    
    def save_image(
        self,
        image: Image.Image,
        output_format: str,
        quality: int,
        output_path: Path
    ) -> int:
        """Сохранение изображения в файл."""
        save_params = {}
        
        # Параметры сохранения для разных форматов
        if output_format == "JPEG":
            save_params = {'quality': quality, 'optimize': True}
        elif output_format == "PNG":
            save_params = {'optimize': True}
        elif output_format == "WEBP":
            save_params = {'quality': quality}
        
        image.save(output_path, format=output_format, **save_params)
        
        return output_path.stat().st_size

# Зависимости
def get_image_processor() -> ImageProcessor:
    """Получение процессора изображений."""
    return ImageProcessor()

# Эндпоинты
@app.post(
    "/image/process",
    response_model=ImageProcessResponse,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Обработка и изменение размера изображения",
    description="Загрузите изображение и укажите параметры для изменения размера и обработки"
)
async def process_image(
    file: UploadFile = File(..., description="Изображение для обработки"),
    params: ImageResizeRequest = Depends(),
    processor: ImageProcessor = Depends(get_image_processor)
):
    """
    Обработка и изменение размера загруженного изображения.
    
    Поддерживаемые форматы: JPEG, PNG, GIF, BMP, WebP, TIFF
    Максимальный размер файла: 50MB
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())
    
    try:
        # Валидация файла
        is_valid, error_message = validate_image_file(file)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_message)
        
        # Чтение файла
        file_data = await file.read()
        
        # Проверка размера файла
        if len(file_data) > config.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Файл слишком большой. Максимальный размер: {config.MAX_FILE_SIZE // (1024*1024)}MB"
            )
        
        # Хеш файла для кэширования
        file_hash = hashlib.md5(file_data).hexdigest()
        
        # Проверка параметров
        if params.width or params.height:
            is_valid, error_message = validate_resize_params(
                params.width or 100,
                params.height or 100,
                params.upscale
            )
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_message)
        
        # Проверка кэша
        cache_key = image_cache.get_key(file_hash, params.dict())
        cached_file = image_cache.get(cache_key)
        
        if cached_file and cached_file.exists():
            # Возвращаем кэшированный файл
            logger.info(f"Использован кэш для запроса {request_id}")
            
            return ImageProcessResponse(
                request_id=request_id,
                original_filename=file.filename,
                processed_filename=cached_file.name,
                original_size=(0, 0),  # Неизвестно для кэша
                processed_size=(params.width or 0, params.height or 0),
                file_size=cached_file.stat().st_size,
                format=params.format,
                processing_time=time.time() - start_time,
                download_url=f"/image/download/{cached_file.name}",
                expires_at=datetime.fromtimestamp(time.time() + config.FILE_TTL)
            )
        
        # Обработка изображения
        image, output_format = await processor.process_image(
            file_data,
            file.filename,
            params
        )
        
        # Сохранение оригинального изображения (для справки)
        original_path = config.UPLOAD_DIR / f"{request_id}_original_{file.filename}"
        with open(original_path, 'wb') as f:
            f.write(file_data)
        
        # Генерация имени файла для результата
        timestamp = int(time.time())
        processed_filename = f"{request_id}_{timestamp}_{params.width or 'auto'}x{params.height or 'auto'}.{output_format.lower()}"
        processed_path = config.PROCESSED_DIR / processed_filename
        
        # Сохранение обработанного изображения
        file_size = processor.save_image(
            image,
            output_format,
            params.quality,
            processed_path
        )
        
        # Добавление в кэш
        image_cache.set(cache_key, processed_path)
        
        # Удаление старых файлов
        await cleanup_old_files()
        
        processing_time = time.time() - start_time
        
        logger.info(f"Обработан запрос {request_id} за {processing_time:.2f}с")
        
        return ImageProcessResponse(
            request_id=request_id,
            original_filename=file.filename,
            processed_filename=processed_filename,
            original_size=image.size if hasattr(image, 'size') else (0, 0),
            processed_size=image.size if hasattr(image, 'size') else (0, 0),
            file_size=file_size,
            format=output_format,
            processing_time=processing_time,
            download_url=f"/image/download/{processed_filename}",
            expires_at=datetime.fromtimestamp(time.time() + config.FILE_TTL)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке изображения {request_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="Internal Server Error",
                detail=str(e),
                request_id=request_id
            ).dict()
        )

@app.get(
    "/image/download/{filename}",
    response_class=FileResponse,
    summary="Скачивание обработанного изображения",
    description="Получение обработанного изображения по имени файла"
)
async def download_image(filename: str):
    """Скачивание обработанного изображения."""
    file_path = config.PROCESSED_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    # Определение MIME-типа
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type:
        mime_type = "application/octet-stream"
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=mime_type
    )

@app.get(
    "/image/info/{filename}",
    summary="Информация об обработанном изображении",
    description="Получение метаинформации об обработанном изображении"
)
async def get_image_info(filename: str):
    """Получение информации об изображении."""
    file_path = config.PROCESSED_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    try:
        with Image.open(file_path) as img:
            return {
                "filename": filename,
                "format": img.format,
                "size": img.size,
                "mode": img.mode,
                "file_size": file_path.stat().st_size,
                "created_at": datetime.fromtimestamp(file_path.stat().st_ctime),
                "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime)
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Невозможно прочитать информацию об изображении: {str(e)}")

async def cleanup_old_files():
    """Очистка старых файлов."""
    current_time = time.time()
    
    for directory in [config.UPLOAD_DIR, config.PROCESSED_DIR]:
        for file_path in directory.glob("*"):
            if current_time - file_path.stat().st_mtime > config.FILE_TTL:
                try:
                    file_path.unlink()
                    logger.info(f"Удален старый файл: {file_path}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении файла {file_path}: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """Действия при запуске приложения."""
    logger.info("Запуск сервиса обработки изображений")
    # Запуск периодической очистки старых файлов
    asyncio.create_task(periodic_cleanup())

async def periodic_cleanup():
    """Периодическая очистка старых файлов."""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        await cleanup_old_files()

@app.on_event("shutdown")
async def shutdown_event():
    """Действия при остановке приложения."""
    logger.info("Остановка сервиса обработки изображений")
    processor = get_image_processor()
    processor.executor.shutdown(wait=True)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )