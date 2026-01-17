import io
import boto3
from PIL import Image
from fastapi import FastAPI, UploadFile, File, HTTPException
from botocore.exceptions import NoCredentialsError

app = FastAPI()

class AvatarProcessor:
    """
    Сервис для валидации, обработки и загрузки аватаров в облако.
    """
    
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
    TARGET_SIZE = (200, 200)
    
    def __init__(self):
        # Настройки S3 (в продакшене брать из .env)
        self.s3_client = boto3.client('s3')
        self.bucket_name = "user-avatars-bucket"

    def process_image(self, file_content: bytes) -> io.BytesIO:
        """Изменяет размер изображения и конвертирует в оптимизированный формат."""
        try:
            with Image.open(io.BytesIO(file_content)) as img:
                # Конвертация в RGB (убирает альфа-канал для JPEG или оптимизации)
                img = img.convert("RGB")
                
                # Сохранение пропорций с обрезкой (Thumbnail) или жесткий ресайз
                img = img.resize(self.TARGET_SIZE, Image.Resampling.LANCZOS)
                
                output = io.BytesIO()
                img.save(output, format="JPEG", quality=85)
                output.seek(0)
                return output
        except Exception as e:
            raise ValueError(f"Ошибка обработки изображения: {e}")

    async def upload_to_cloud(self, file_data: io.BytesIO, filename: str) -> str:
        """Загружает файл в S3 и возвращает URL."""
        try:
            s3_path = f"avatars/{filename}.jpg"
            self.s3_client.upload_fileobj(
                file_data, 
                self.bucket_name, 
                s3_path,
                ExtraArgs={"ContentType": "image/jpeg"}
            )
            return f"https://{self.bucket_name}.s3.amazonaws.com/{s3_path}"
        except NoCredentialsError:
            raise HTTPException(status_code=500, detail="Ошибка доступа к облаку")

processor = AvatarProcessor()

@app.post("/upload-avatar")
async def upload_avatar(file: UploadFile = File(...)):
    """
    Эндпоинт для обработки аватара.
    """
    # 1. Проверка типа файла
    if file.content_type not in processor.ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Недопустимый формат файла")

    # 2. Чтение данных
    content = await file.read()
    
    # 3. Обработка изображения
    try:
        processed_image = processor.process_image(content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 4. Загрузка в облако
    file_url = await processor.upload_to_cloud(processed_image, file.filename.split('.')[0])
    
    return {
        "status": "success",
        "avatar_url": file_url,
        "size": processor.TARGET_SIZE
    }

if __name__ == "__main__":
    print("AvatarProcessor готов к обработке изображений.")