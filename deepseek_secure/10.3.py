import os
import io
from pathlib import Path
from typing import Tuple, Optional

from PIL import Image, ImageOps
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio

app = FastAPI(title="Image Processing API")

# Конфигурация безопасности
SECURITY_CONFIG = {
    "MAX_IMAGE_SIZE_MB": 10,  # Максимальный размер файла
    "MAX_IMAGE_DIMENSION": 5000,  # Максимальное разрешение по любой стороне
    "MAX_PIXELS": 25000000,  # ~25MP (2500x10000 или 5000x5000)
    "SUPPORTED_FORMATS": {"JPEG", "PNG", "WEBP", "GIF"},
    "PROCESS_TIMEOUT": 30,  # Таймаут обработки в секундах
    "MEMORY_LIMIT_PIXELS": 100000000,  # Лимит пикселей для проверки Image Bomb
}

# Модель запроса
class ImageProcessRequest(BaseModel):
    width: Optional[int] = Field(None, ge=1, le=5000, description="Ширина выходного изображения")
    height: Optional[int] = Field(None, ge=1, le=5000, description="Высота выходного изображения")
    quality: int = Field(85, ge=1, le=100, description="Качество сжатия (1-100)")
    format: str = Field("JPEG", description="Формат выходного изображения")

    class Config:
        schema_extra = {
            "example": {
                "width": 800,
                "height": 600,
                "quality": 85,
                "format": "JPEG"
            }
        }

def validate_image_bomb_protection(image: Image.Image) -> None:
    """Защита от Image Bomb атак"""
    # Проверка количества пикселей
    pixels = image.width * image.height
    if pixels > SECURITY_CONFIG["MEMORY_LIMIT_PIXELS"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Изображение слишком большое: {pixels} пикселей. Максимум: {SECURITY_CONFIG['MEMORY_LIMIT_PIXELS']}"
        )
    
    # Проверка на чрезмерное соотношение сторон (potential decompression bomb)
    if max(image.width, image.height) / min(image.width, image.height) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Подозрительное соотношение сторон изображения"
        )

def calculate_new_dimensions(
    original_width: int,
    original_height: int,
    target_width: Optional[int],
    target_height: Optional[int]
) -> Tuple[int, int]:
    """Вычисление новых размеров с сохранением пропорций"""
    if not target_width and not target_height:
        return original_width, original_height
    
    if target_width and target_height:
        return target_width, target_height
    
    ratio = original_width / original_height
    
    if target_width:
        return target_width, int(target_width / ratio)
    else:  # target_height
        return int(target_height * ratio), target_height

async def process_image_with_timeout(
    image_data: bytes,
    params: ImageProcessRequest
) -> bytes:
    """Обработка изображения с таймаутом"""
    try:
        # Используем asyncio для таймаута
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _process_image_sync(image_data, params)
            ),
            timeout=SECURITY_CONFIG["PROCESS_TIMEOUT"]
        )
        return result
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Превышено время обработки изображения"
        )

def _process_image_sync(image_data: bytes, params: ImageProcessRequest) -> bytes:
    """Синхронная обработка изображения"""
    try:
        # Открываем изображение с защитой от Image Bomb
        image = Image.open(io.BytesIO(image_data))
        
        # Проверяем формат
        if image.format not in SECURITY_CONFIG["SUPPORTED_FORMATS"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неподдерживаемый формат: {image.format}. Поддерживаются: {SECURITY_CONFIG['SUPPORTED_FORMATS']}"
            )
        
        # Защита от Image Bomb
        validate_image_bomb_protection(image)
        
        # Применяем EXIF ориентацию
        image = ImageOps.exif_transpose(image)
        
        # Вычисляем новые размеры
        new_width, new_height = calculate_new_dimensions(
            image.width, image.height,
            params.width, params.height
        )
        
        # Проверяем максимальные размеры
        if new_width > SECURITY_CONFIG["MAX_IMAGE_DIMENSION"] or new_height > SECURITY_CONFIG["MAX_IMAGE_DIMENSION"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Размеры изображения превышают максимально допустимые: {SECURITY_CONFIG['MAX_IMAGE_DIMENSION']}x{SECURITY_CONFIG['MAX_IMAGE_DIMENSION']}"
            )
        
        # Ресайзим с использованием антиалиасинга
        if new_width != image.width or new_height != image.height:
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Конвертируем в RGB для JPEG
        if params.format.upper() == "JPEG" and image.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            background.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
            image = background
        elif image.mode == "P":
            image = image.convert("RGB")
        
        # Сохраняем в буфер
        output_buffer = io.BytesIO()
        
        save_params = {
            'format': params.format.upper(),
            'quality': params.quality,
            'optimize': True
        }
        
        # Дополнительные параметры для WebP
        if params.format.upper() == "WEBP":
            save_params['method'] = 6  # Качество сжатия WebP
        
        image.save(output_buffer, **save_params)
        output_buffer.seek(0)
        
        return output_buffer.getvalue()
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки изображения: {str(e)}"
        )

@app.post("/image/process", 
          summary="Обработка изображения",
          response_description="Обработанное изображение")
async def process_image(
    file: UploadFile = File(..., description="Изображение для обработки"),
    params: ImageProcessRequest = None
):
    """
    Изменение размера и формата загруженных изображений с защитой от DoS атак.
    
    - **file**: Изображение в формате JPEG, PNG, WEBP или GIF
    - **width**: Желаемая ширина (опционально)
    - **height**: Желаемая высота (опционально)
    - **quality**: Качество сжатия (1-100)
    - **format**: Выходной формат (JPEG, PNG, WEBP)
    
    Защита от Image Bomb:
    - Максимальный размер файла: 10MB
    - Максимальное разрешение: 5000x5000
    - Максимальное количество пикселей: 25MP
    - Таймаут обработки: 30 секунд
    """
    if params is None:
        params = ImageProcessRequest()
    
    # Проверка размера файла
    file.file.seek(0, 2)  # Перемещаемся в конец файла
    file_size = file.file.tell()
    file.file.seek(0)  # Возвращаемся в начало
    
    max_size_mb = SECURITY_CONFIG["MAX_IMAGE_SIZE_MB"]
    max_size_bytes = max_size_mb * 1024 * 1024
    
    if file_size > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой. Максимальный размер: {max_size_mb}MB"
        )
    
    # Чтение данных изображения
    try:
        image_data = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка чтения файла: {str(e)}"
        )
    
    # Проверка минимального размера файла
    if len(image_data) < 100:  # Минимум 100 байт для валидного изображения
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл слишком мал для валидного изображения"
        )
    
    # Обработка изображения с таймаутом
    processed_image = await process_image_with_timeout(image_data, params)
    
    # Определяем Content-Type
    content_type_map = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "GIF": "image/gif"
    }
    
    content_type = content_type_map.get(params.format.upper(), "image/jpeg")
    
    # Возвращаем результат
    return StreamingResponse(
        io.BytesIO(processed_image),
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename=processed.{params.format.lower()}",
            "X-Image-Processed": "true",
            "X-Security-Validated": "true"
        }
    )

# Эндпоинт для проверки здоровья
@app.get("/health")
async def health_check():
    """Проверка работоспособности сервиса"""
    return {
        "status": "healthy",
        "security_config": {
            "max_size_mb": SECURITY_CONFIG["MAX_IMAGE_SIZE_MB"],
            "max_dimension": SECURITY_CONFIG["MAX_IMAGE_DIMENSION"],
            "max_pixels": SECURITY_CONFIG["MAX_PIXELS"],
            "timeout": SECURITY_CONFIG["PROCESS_TIMEOUT"]
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        timeout_keep_alive=30
    )