import hashlib
import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from pathlib import Path

app = FastAPI(title="Distro Upload Service")

# Директория для хранения загруженных дистрибутивов
UPLOAD_DIR = Path("distros")
UPLOAD_DIR.mkdir(exist_ok=True)

class HashVerifier:
    """Инструмент для вычисления хеша файла по частям (streaming)."""
    
    @staticmethod
    def calculate_sha256(file_object) -> str:
        sha256_hash = hashlib.sha256()
        # Читаем файл кусками по 64КБ, чтобы не перегружать RAM
        for byte_block in iter(lambda: file_object.read(65536), b""):
            sha256_hash.update(byte_block)
        
        # Возвращаем указатель файла в начало после чтения
        file_object.seek(0)
        return sha256_hash.hexdigest()

@app.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_distro(
    file: UploadFile = File(...),
    expected_hash: str = Form(...)
):
    """
    Эндпоинт загрузки файла с обязательной проверкой целостности.
    """
    verifier = HashVerifier()
    
    # 1. Вычисляем фактический хеш загруженного контента
    # Используем file.file для доступа к объекту SpooledTemporaryFile
    actual_hash = verifier.calculate_sha256(file.file)
    
    # 2. Сверяем хеши (приводим к нижнему регистру для надежности)
    if actual_hash.lower() != expected_hash.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Integrity check failed",
                "expected": expected_hash.lower(),
                "actual": actual_hash
            }
        )

    # 3. Сохраняем файл, если проверка пройдена
    file_path = UPLOAD_DIR / file.filename
    try:
        with open(file_path, "wb") as buffer:
            # Снова читаем с начала и записываем на диск
            file.file.seek(0)
            while chunk := file.file.read(65536):
                buffer.write(chunk)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {str(e)}"
        )

    return {
        "filename": file.filename,
        "status": "verified_and_saved",
        "sha256": actual_hash
    }

if __name__ == "__main__":
    import uvicorn
    # Запуск сервера
    # uvicorn.run(app, host="0.0.0.0", port=8000)
    print("Сервис загрузки дистрибутивов запущен.")