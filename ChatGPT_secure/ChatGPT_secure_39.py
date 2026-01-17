import hashlib
import os
import tempfile
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from pydantic import BaseModel, constr

# =========================
# CONFIGURATION
# =========================

UPLOAD_DIR = Path("./distributions")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_SIZE = 1024 * 1024  # 1 MB
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB


# =========================
# RESPONSE SCHEMA
# =========================

class UploadResult(BaseModel):
    filename: str
    sha256: str
    status: str


# =========================
# HASHING UTILITIES
# =========================

def stream_file_and_hash(file: UploadFile) -> tuple[str, Path]:
    """
    Потоково читает файл, вычисляет SHA-256 и сохраняет во временный файл.
    """
    hasher = hashlib.sha256()
    total_read = 0

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        while True:
            chunk = file.file.read(CHUNK_SIZE)
            if not chunk:
                break

            total_read += len(chunk)
            if total_read > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Файл превышает допустимый размер",
                )

            hasher.update(chunk)
            tmp.write(chunk)

        tmp_path = Path(tmp.name)

    return hasher.hexdigest(), tmp_path


# =========================
# FASTAPI APP
# =========================

app = FastAPI(title="Distribution Upload Service")


@app.post(
    "/upload",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
)
def upload_distribution(
    file: UploadFile = File(...),
    expected_sha256: constr(min_length=64, max_length=64) = Form(...),
) -> UploadResult:
    calculated_hash, tmp_path = stream_file_and_hash(file)

    if not hashlib.compare_digest(calculated_hash, expected_sha256.lower()):
        os.unlink(tmp_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Контрольная сумма не совпадает",
        )

    final_path = UPLOAD_DIR / file.filename
    tmp_path.replace(final_path)

    return UploadResult(
        filename=file.filename,
        sha256=calculated_hash,
        status="uploaded",
    )
