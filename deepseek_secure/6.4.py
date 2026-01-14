import os
import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, status
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps
import PIL
from pydantic import BaseModel, Field
import io

# Конфигурация
class AvatarConfig:
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
    ALLOWED_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp"]
    RESIZE_WIDTH = 300
    RESIZE_HEIGHT = 300
    AVATAR_DIR = Path("uploads/avatars")
    MAX_IMAGE_PIXELS = 50_000_000  # Защита от декомпрессионной бомбы
    
    # Создаем директорию, если не существует
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)

class AvatarResponse(BaseModel):
    success: bool = Field(..., description="Статус операции")
    avatar_url: Optional[str] = Field(None, description="URL загруженного аватара")
    message: Optional[str] = Field(None, description="Сообщение об ошибке или успехе")
    file_size_kb: Optional[float] = Field(None, description="Размер файла в КБ")

app = FastAPI(title="User Profile API", version="1.0.0")

def validate_image_file(file: UploadFile) -> Tuple[bool, str]:
    """Валидация загружаемого файла"""
    
    # Проверка типа содержимого
    if file.content_type not in AvatarConfig.ALLOWED_CONTENT_TYPES:
        return False, f"Неподдерживаемый формат. Разрешены: {', '.join(AvatarConfig.ALLOWED_CONTENT_TYPES)}"
    
    # Чтение и проверка размера файла
    file.file.seek(0, 2)  # Перемещаемся в конец файла
    file_size = file.file.tell()
    file.file.seek(0)  # Возвращаемся в начало
    
    if file_size > AvatarConfig.MAX_FILE_SIZE:
        return False, f"Файл слишком большой. Максимальный размер: {AvatarConfig.MAX_FILE_SIZE // 1024 // 1024}MB"
    
    if file_size == 0:
        return False, "Файл пустой"
    
    return True, ""

def generate_unique_filename(original_filename: str, user_id: int) -> str:
    """Генерация уникального имени файла"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_ext = Path(original_filename).suffix.lower()
    unique_id = uuid.uuid4().hex[:8]
    
    return f"avatar_{user_id}_{timestamp}_{unique_id}{file_ext}"

def resize_and_save_image(
    image_data: bytes,
    output_path: Path,
    user_id: int
) -> Tuple[bool, str, Optional[Tuple[int, int]]]:
    """Изменение размера и сохранение изображения"""
    
    try:
        # Устанавливаем лимит пикселей для защиты от декомпрессионной бомбы
        Image.MAX_IMAGE_PIXELS = AvatarConfig.MAX_IMAGE_PIXELS
        
        # Открываем изображение из байтов
        with Image.open(io.BytesIO(image_data)) as img:
            # Конвертируем в RGB, если необходимо
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Получаем исходные размеры
            original_width, original_height = img.size
            
            # Изменяем размер с сохранением пропорций
            img = ImageOps.fit(
                img,
                (AvatarConfig.RESIZE_WIDTH, AvatarConfig.RESIZE_HEIGHT),
                method=Image.Resampling.LANCZOS,
                bleed=0.0,
                centering=(0.5, 0.5)
            )
            
            # Определяем формат сохранения на основе расширения
            output_format = 'JPEG' if output_path.suffix.lower() in ['.jpg', '.jpeg'] else 'PNG'
            
            # Параметры сохранения
            save_kwargs = {}
            if output_format == 'JPEG':
                save_kwargs['quality'] = 85
                save_kwargs['optimize'] = True
                save_kwargs['progressive'] = True
            
            # Сохраняем изображение
            img.save(output_path, format=output_format, **save_kwargs)
            
            return True, "", (original_width, original_height)
            
    except PIL.Image.DecompressionBombError:
        return False, "Изображение слишком большое и может быть декомпрессионной бомбой", None
    except Exception as e:
        return False, f"Ошибка обработки изображения: {str(e)}", None

def calculate_file_hash(file_path: Path) -> str:
    """Вычисление хеша файла для проверки уникальности"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

@app.post(
    "/profile/avatar",
    response_model=AvatarResponse,
    status_code=status.HTTP_200_OK,
    summary="Загрузка аватара пользователя",
    description="Загрузка и обработка аватара пользователя с валидацией и изменением размера"
)
async def upload_avatar(
    user_id: int = Field(..., description="ID пользователя", gt=0),
    file: UploadFile = File(..., description="Изображение для аватара (JPEG, PNG, WebP)")
):
    """
    Загрузка аватара пользователя.
    
    - **user_id**: ID пользователя (обязательно)
    - **file**: Файл изображения (макс. 5MB, JPEG/PNG/WebP)
    
    Возвращает URL загруженного аватара или сообщение об ошибке.
    """
    
    # Валидация файла
    is_valid, error_message = validate_image_file(file)
    if not is_valid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=AvatarResponse(
                success=False,
                message=error_message
            ).dict()
        )
    
    # Чтение файла
    try:
        contents = await file.read()
        file_size_kb = len(contents) / 1024
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_BAD_REQUEST,
            content=AvatarResponse(
                success=False,
                message=f"Ошибка чтения файла: {str(e)}"
            ).dict()
        )
    
    # Генерация имени файла и пути
    filename = generate_unique_filename(file.filename, user_id)
    output_path = AvatarConfig.AVATAR_DIR / filename
    
    # Изменение размера и сохранение
    success, error_message, original_dimensions = resize_and_save_image(
        contents, output_path, user_id
    )
    
    if not success:
        # Удаляем частично сохраненный файл, если есть
        if output_path.exists():
            output_path.unlink()
        
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=AvatarResponse(
                success=False,
                message=error_message
            ).dict()
        )
    
    # Вычисляем хеш файла (можно сохранить в БД для проверки дубликатов)
    file_hash = calculate_file_hash(output_path)
    
    # Формируем URL (в реальном проекте используйте настройки хоста)
    avatar_url = f"/static/avatars/{filename}"
    
    # Здесь можно сохранить информацию в БД
    # save_avatar_to_db(user_id, filename, avatar_url, file_hash, file_size_kb, original_dimensions)
    
    return AvatarResponse(
        success=True,
        avatar_url=avatar_url,
        message=f"Аватар успешно загружен. Размер: {file_size_kb:.2f} KB",
        file_size_kb=round(file_size_kb, 2)
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Обработчик HTTP исключений"""
    return JSONResponse(
        status_code=exc.status_code,
        content=AvatarResponse(
            success=False,
            message=exc.detail
        ).dict()
    )

# Запуск приложения (для разработки)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "avatar_upload:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )