import io
from typing import Tuple, Optional
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
import boto3
from PIL import Image
import magic
from botocore.exceptions import ClientError
from pydantic import BaseModel


class AvatarResponse(BaseModel):
    """Модель ответа для загрузки аватара."""
    success: bool
    message: str
    avatar_url: Optional[str] = None
    file_size: Optional[int] = None
    dimensions: Optional[Tuple[int, int]] = None


class CloudStorage:
    """Класс для работы с облачным хранилищем (на примере AWS S3)."""
    
    def __init__(self, bucket_name: str, region: str = 'us-east-1'):
        """
        Инициализация клиента облачного хранилища.
        
        Args:
            bucket_name: Название S3 bucket
            region: Регион AWS
        """
        self.bucket_name = bucket_name
        self.s3_client = boto3.client('s3', region_name=region)
    
    def upload_file(self, file_content: bytes, file_name: str, 
                   content_type: str) -> Optional[str]:
        """
        Загружает файл в облачное хранилище.
        
        Args:
            file_content: Байтовое содержимое файла
            file_name: Имя файла для сохранения
            content_type: MIME-тип файла
        
        Returns:
            URL загруженного файла или None при ошибке
        """
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=file_name,
                Body=file_content,
                ContentType=content_type,
                ACL='public-read'
            )
            
            # Генерируем URL файла
            url = f"https://{self.bucket_name}.s3.amazonaws.com/{file_name}"
            return url
            
        except ClientError as e:
            print(f"Ошибка загрузки в S3: {e}")
            return None


class AvatarProcessor:
    """Класс для обработки аватаров."""
    
    # Поддерживаемые форматы изображений
    SUPPORTED_FORMATS = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
    
    # Целевой размер аватара
    TARGET_SIZE = (200, 200)
    
    # Максимальный размер файла (5MB)
    MAX_FILE_SIZE = 5 * 1024 * 1024
    
    def __init__(self, cloud_storage: CloudStorage):
        """
        Инициализация процессора аватаров.
        
        Args:
            cloud_storage: Экземпляр облачного хранилища
        """
        self.cloud_storage = cloud_storage
        self.mime = magic.Magic(mime=True)
    
    async def process_avatar(self, file: UploadFile, user_id: str) -> AvatarResponse:
        """
        Обрабатывает загруженный аватар.
        
        Args:
            file: Загруженный файл
            user_id: ID пользователя
        
        Returns:
            AvatarResponse с результатом обработки
        """
        try:
            # Проверяем размер файла
            file_content = await file.read()
            if len(file_content) > self.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"Файл слишком большой. Максимальный размер: {self.MAX_FILE_SIZE/1024/1024}MB"
                )
            
            # Определяем MIME-тип
            mime_type = self.mime.from_buffer(file_content)
            
            # Проверяем поддерживаемый формат
            if mime_type not in self.SUPPORTED_FORMATS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Неподдерживаемый формат изображения. Поддерживаемые: {', '.join(self.SUPPORTED_FORMATS)}"
                )
            
            # Обрабатываем изображение
            processed_image, dimensions = self._process_image(file_content)
            
            # Генерируем имя файла
            file_extension = self._get_extension_from_mime(mime_type)
            file_name = f"avatars/{user_id}/avatar_{user_id}{file_extension}"
            
            # Загружаем в облачное хранилище
            avatar_url = self.cloud_storage.upload_file(
                processed_image,
                file_name,
                mime_type
            )
            
            if not avatar_url:
                raise HTTPException(
                    status_code=500,
                    detail="Ошибка при загрузке файла в облачное хранилище"
                )
            
            return AvatarResponse(
                success=True,
                message="Аватар успешно загружен и обработан",
                avatar_url=avatar_url,
                file_size=len(processed_image),
                dimensions=dimensions
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка обработки аватара: {str(e)}"
            )
    
    def _process_image(self, image_content: bytes) -> Tuple[bytes, Tuple[int, int]]:
        """
        Обрабатывает изображение: изменяет размер и оптимизирует.
        
        Args:
            image_content: Байтовое содержимое изображения
        
        Returns:
            Кортеж (обработанные байты, размеры)
        """
        # Открываем изображение
        image = Image.open(io.BytesIO(image_content))
        
        # Конвертируем в RGB если нужно (для PNG с альфа-каналом)
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background
        
        # Изменяем размер с сохранением пропорций
        image.thumbnail(self.TARGET_SIZE, Image.Resampling.LANCZOS)
        
        # Конвертируем в байты
        output_buffer = io.BytesIO()
        image.save(output_buffer, format='JPEG', quality=85, optimize=True)
        
        return output_buffer.getvalue(), image.size
    
    def _get_extension_from_mime(self, mime_type: str) -> str:
        """Возвращает расширение файла на основе MIME-типа."""
        extensions = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/webp': '.webp',
            'image/gif': '.gif'
        }
        return extensions.get(mime_type, '.jpg')


# Создаем FastAPI приложение
app = FastAPI(
    title="Avatar Processing Service",
    description="Сервис для обработки и загрузки аватаров пользователей",
    version="1.0.0"
)


# Зависимости
def get_cloud_storage():
    """Возвращает экземпляр облачного хранилища."""
    # В реальном приложении эти значения должны быть в конфигурации
    return CloudStorage(bucket_name="my-avatars-bucket")


def get_avatar_processor(cloud_storage: CloudStorage = Depends(get_cloud_storage)):
    """Возвращает экземпляр процессора аватаров."""
    return AvatarProcessor(cloud_storage)


# Эндпоинты
@app.post("/upload-avatar/{user_id}", response_model=AvatarResponse)
async def upload_avatar(
    user_id: str,
    file: UploadFile = File(...),
    processor: AvatarProcessor = Depends(get_avatar_processor)
):
    """
    Загружает и обрабатывает аватар пользователя.
    
    Args:
        user_id: ID пользователя
        file: Файл изображения
    
    Returns:
        Результат обработки аватара
    """
    return await processor.process_avatar(file, user_id)


@app.get("/health")
async def health_check():
    """Проверка здоровья сервиса."""
    return {"status": "healthy", "service": "avatar-processor"}


# Пример использования (не для production)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)