import hashlib
import hmac
import os
import shutil
from pathlib import Path
from typing import Final

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status

app = FastAPI()

# --- Конфигурация хранилища ---
UPLOAD_DIR: Final[Path] = Path("./distributions")
CHUNK_SIZE: Final[int] = 1024 * 1024  # 1 MB для потоковой обработки
MAX_FILE_SIZE: Final[int] = 1024 * 1024 * 500  # Лимит 500 MB

# Создаем директорию, если она не существует
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/upload-dist", status_code=status.HTTP_201_CREATED)
async def upload_distribution(
    expected_hash: str = Form(..., min_length=64, max_length=64, pattern=r"^[a-fA-F0-9]+$"),
    file: UploadFile = File(...)
):
    """
    Эндпоинт для безопасной загрузки дистрибутивов с проверкой SHA-256.
    """
    
    sha256_hash = hashlib.sha256()
    temp_file_path = UPLOAD_DIR / f"temp_{file.filename}_{os.urandom(4).hex()}"
    
    try:
        # 1. Открываем файл для записи во временную локацию
        with open(temp_file_path, "wb") as buffer:
            total_size = 0
            
            # 2. Читаем файл потоково (Chunk-based processing)
            while chunk := await file.read(CHUNK_SIZE):
                total_size += len(chunk)
                
                # Защита от слишком больших файлов (DoS)
                if total_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File size exceeds limit."
                    )
                
                # Обновляем хеш текущим фрагментом
                sha256_hash.update(chunk)
                # Записываем фрагмент на диск
                buffer.write(chunk)

        # 3. Финальное вычисление хеша
        calculated_hash = sha256_hash.hexdigest()

        # 4. Сравнение хешей в постоянное время (защита от атак по времени)
        # Хотя это файл, использование compare_digest — хорошая практика безопасности
        if not hmac.compare_digest(calculated_hash.lower(), expected_hash.lower()):
            if temp_file_path.exists():
                os.remove(temp_file_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Integrity check failed: Checksum mismatch."
            )

        # 5. Подтверждение загрузки: перемещение из временной папки в постоянную
        final_destination = UPLOAD_DIR / file.filename
        shutil.move(str(temp_file_path), str(final_destination))
        
        return {
            "status": "success",
            "filename": file.filename,
            "sha256": calculated_hash
        }

    except Exception as e:
        # Гарантированная очистка при любой ошибке
        if temp_file_path.exists():
            os.remove(temp_file_path)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload aborted due to server error: {str(e)}"
        )