import io
import uuid
from typing import Tuple

from fastapi import FastAPI, UploadFile, File, HTTPException, status
from PIL import Image
from pydantic import BaseModel
from starlette.responses import JSONResponse


# =========================
# CONSTANTS
# =========================

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG"}
TARGET_SIZE: Tuple[int, int] = (200, 200)


# =========================
# CLOUD STORAGE (MOCK)
# =========================

class CloudStorageClient:
    """
    Упрощённый клиент облачного хранилища.
    """

    def upload(self, filename: str, data: bytes) -> str:
        # Здесь должна быть интеграция с S3 / GCS / Azure Blob
        # Возвращаем публичный URL
        return f"https://cdn.example.com/avatars/{filename}"


# =========================
# RESPONSE SCHEMA
# =========================

class AvatarUploadResponse(BaseModel):
    avatar_url: str


# =========================
# IMAGE SERVICE
# =========================

class AvatarService:
    """
    Сервис обработки аватаров.
    """

    def __init__(self, storage: CloudStorageClient) -> None:
        self._storage = storage

    def process_and_store(self, file: UploadFile) -> str:
        raw_bytes = self._read_and_validate_size(file)
        image = self._validate_and_load_image(raw_bytes)
        resized_image = self._resize_image(image)

        filename = self._generate_filename(image.format)
        image_bytes = self._serialize_image(resized_image, image.format)

        return self._storage.upload(filename, image_bytes)

    def _read_and_validate_size(self, file: UploadFile) -> bytes:
        data = file.file.read(MAX_FILE_SIZE_BYTES + 1)
        if len(data) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Файл превышает допустимый размер",
            )
        return data

    def _validate_and_load_image(self, data: bytes) -> Image.Image:
        try:
            image = Image.open(io.BytesIO(data))
            image.verify()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Файл не является допустимым изображением",
            )

        image = Image.open(io.BytesIO(data))

        if image.format not in ALLOWED_IMAGE_FORMATS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Недопустимый формат изображения",
            )

        return image

    def _resize_image(self, image: Image.Image) -> Image.Image:
        return image.resize(TARGET_SIZE)

    def _serialize_image(self, image: Image.Image, fmt: str) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format=fmt)
        return buffer.getvalue()

    def _generate_filename(self, fmt: str) -> str:
        extension = fmt.lower()
        return f"{uuid.uuid4().hex}.{extension}"


# =========================
# FASTAPI APPLICATION
# =========================

app = FastAPI(
    title="Avatar Processing Service",
    version="1.0.0",
)

storage_client = CloudStorageClient()
avatar_service = AvatarService(storage_client)


# =========================
# ENDPOINT
# =========================

@app.post(
    "/avatars/upload",
    response_model=AvatarUploadResponse,
)
def upload_avatar(file: UploadFile = File(...)) -> JSONResponse:
    avatar_url = avatar_service.process_and_store(file)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"avatar_url": avatar_url},
    )
