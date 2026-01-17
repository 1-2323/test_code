from io import BytesIO
from typing import Protocol

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    status,
)
from PIL import Image


# =========================
# Константы
# =========================

ALLOWED_CONTENT_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

AVATAR_SIZE: tuple[int, int] = (200, 200)


# =========================
# Контракт облачного хранилища
# =========================

class CloudStorage(Protocol):
    """
    Контракт облачного хранилища.
    """

    def upload(
        self,
        path: str,
        content: bytes,
        content_type: str,
    ) -> str:
        """
        Загружает файл и возвращает публичный URL.
        """
        ...


# =========================
# Пример реализации хранилища
# =========================

class InMemoryCloudStorage:
    """
    Демонстрационная реализация облачного хранилища.
    """

    def upload(
        self,
        path: str,
        content: bytes,
        content_type: str,
    ) -> str:
        # Здесь может быть S3 / GCS / Azure Blob
        return f"https://cloud.example.com/{path}"


# =========================
# Сервис обработки аватаров
# =========================

class AvatarService:
    """
    Сервис валидации, обработки и загрузки аватаров.
    """

    def __init__(self, storage: CloudStorage) -> None:
        self._storage = storage

    def process_and_upload(
        self,
        file: UploadFile,
        user_id: int,
    ) -> str:
        """
        Проверяет файл, изменяет размер и сохраняет в облако.
        """
        self._validate_file(file)

        image = self._load_image(file)
        resized = self._resize_image(image)

        buffer = BytesIO()
        resized.save(buffer, format=image.format)
        buffer.seek(0)

        path = f"avatars/{user_id}.{image.format.lower()}"

        return self._storage.upload(
            path=path,
            content=buffer.read(),
            content_type=file.content_type,
        )

    # =========================
    # Внутренняя логика
    # =========================

    def _validate_file(self, file: UploadFile) -> None:
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported image type",
            )

    def _load_image(self, file: UploadFile) -> Image.Image:
        try:
            image = Image.open(file.file)
            image.verify()
            file.file.seek(0)
            return Image.open(file.file)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image file",
            ) from exc

    def _resize_image(self, image: Image.Image) -> Image.Image:
        return image.convert("RGB").resize(
            AVATAR_SIZE,
            Image.LANCZOS,
        )


# =========================
# FastAPI приложение
# =========================

app = FastAPI(title="Avatar Processing Service")

storage = InMemoryCloudStorage()
avatar_service = AvatarService(storage)


@app.post("/avatars/upload")
def upload_avatar(
    user_id: int,
    file: UploadFile = File(...),
) -> dict:
    """
    Эндпоинт загрузки и обработки аватара.
    """
    avatar_url = avatar_service.process_and_upload(
        file=file,
        user_id=user_id,
    )

    return {
        "avatar_url": avatar_url,
    }
