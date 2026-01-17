import io
import uuid
from typing import Final
from fastapi import FastAPI, UploadFile, File, HTTPException, status
from PIL import Image, UnidentifiedImageError

app = FastAPI()

# --- Константы безопасности ---
MAX_FILE_SIZE: Final[int] = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIME_TYPES: Final[set] = {"image/jpeg", "image/png", "image/webp"}
AVATAR_SIZE: Final[tuple] = (200, 200)

@app.post("/upload-avatar")
async def upload_avatar(file: UploadFile = File(...)):
    """
    Эндпоинт для безопасной загрузки и обработки аватара.
    """
    
    # 1. Проверка размера файла (защита от переполнения диска/памяти)
    # Пытаемся получить размер из заголовков, если нет - читаем аккуратно
    file_content = await file.read(MAX_FILE_SIZE + 1)
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File is too large. Max limit is 5MB."
        )

    # 2. Проверка содержимого (Magic Bytes) через Pillow
    # Мы не доверяем расширению .jpg или .png в имени файла
    try:
        img = Image.open(io.BytesIO(file_content))
        img.verify()  # Проверяем целостность файла
        
        # Переоткрываем для обработки, так как verify() закрывает файл
        img = Image.open(io.BytesIO(file_content))
        
        if img.format.lower() not in [t.split("/")[-1] for t in ALLOWED_MIME_TYPES]:
            raise ValueError("Unsupported image format.")
            
    except (UnidentifiedImageError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image content or unsupported format."
        )

    # 3. Ресайз (изменение размера)
    # Используем метод LANCZOS для сохранения качества
    img = img.convert("RGB") # Нормализуем к RGB (удаляем альфа-каналы или CMYK)
    img.thumbnail(AVATAR_SIZE)
    
    # Создаем холст 200x200 (на случай если картинка была не квадратной)
    final_avatar = Image.new("RGB", AVATAR_SIZE, (255, 255, 255))
    offset = ((AVATAR_SIZE[0] - img.size[0]) // 2, (AVATAR_SIZE[1] - img.size[1]) // 2)
    final_avatar.paste(img, offset)

    # 4. Генерация уникального имени (защита от перезаписи и Path Traversal)
    # Мы полностью игнорируем оригинальное имя файла
    unique_filename = f"{uuid.uuid4().hex}.jpg"

    # 5. Сохранение в буфер (имитация отправки в облако)
    output_buffer = io.BytesIO()
    final_avatar.save(output_buffer, format="JPEG", quality=85)
    output_buffer.seek(0)

    # Здесь должна быть логика загрузки в S3 / Google Cloud Storage
    # upload_to_cloud(output_buffer, unique_filename)

    return {
        "status": "success",
        "filename": unique_filename,
        "content_type": "image/jpeg"
    }