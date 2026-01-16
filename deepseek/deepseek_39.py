import hashlib
import os
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальное хранилище для состояния сервиса
service_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # Инициализация при запуске
    service_state["uploads_dir"] = Path("uploads")
    service_state["uploads_dir"].mkdir(exist_ok=True)
    
    logger.info("File upload service initialized")
    
    yield
    
    # Очистка при остановке
    logger.info("File upload service shutting down")


app = FastAPI(
    title="File Upload Service",
    description="Service for uploading and verifying file distributions",
    version="1.0.0",
    lifespan=lifespan
)


class FileUploadService:
    """Сервис загрузки и проверки файлов"""
    
    @staticmethod
    def calculate_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
        """
        Вычисление хеша файла
        
        Args:
            file_path: Путь к файлу
            algorithm: Алгоритм хеширования
            
        Returns:
            Хеш в виде hex строки
        """
        hash_func = hashlib.new(algorithm)
        
        with open(file_path, "rb") as f:
            # Читаем файл блоками для обработки больших файлов
            for chunk in iter(lambda: f.read(4096), b""):
                hash_func.update(chunk)
        
        return hash_func.hexdigest()
    
    @staticmethod
    async def save_uploaded_file(
        uploaded_file: UploadFile,
        destination_dir: Path,
        max_file_size: int = 100 * 1024 * 1024  # 100 MB
    ) -> Path:
        """
        Сохранение загруженного файла
        
        Args:
            uploaded_file: Загруженный файл
            destination_dir: Директория для сохранения
            max_file_size: Максимальный размер файла в байтах
            
        Returns:
            Путь к сохраненному файлу
        """
        # Создаем безопасное имя файла
        safe_filename = uploaded_file.filename.replace(" ", "_").replace("/", "_")
        file_path = destination_dir / safe_filename
        
        # Проверяем размер файла
        file_size = 0
        
        with open(file_path, "wb") as f:
            while chunk := await uploaded_file.read(8192):
                file_size += len(chunk)
                
                if file_size > max_file_size:
                    # Удаляем частично загруженный файл
                    f.close()
                    os.unlink(file_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File size exceeds limit of {max_file_size} bytes"
                    )
                
                f.write(chunk)
        
        logger.info(f"File saved: {file_path} ({file_size} bytes)")
        return file_path
    
    @staticmethod
    def validate_file_hash(file_path: Path, expected_hash: str) -> Dict[str, Any]:
        """
        Проверка хеша файла
        
        Args:
            file_path: Путь к файлу
            expected_hash: Ожидаемый хеш
            
        Returns:
            Словарь с результатами проверки
        """
        if not file_path.exists():
            return {
                "valid": False,
                "message": "File not found",
                "actual_hash": None
            }
        
        try:
            # Вычисляем фактический хеш
            actual_hash = FileUploadService.calculate_file_hash(file_path)
            
            # Приводим к нижнему регистру для сравнения
            expected_hash_lower = expected_hash.lower()
            actual_hash_lower = actual_hash.lower()
            
            is_valid = actual_hash_lower == expected_hash_lower
            
            return {
                "valid": is_valid,
                "message": "Hash matches" if is_valid else "Hash mismatch",
                "actual_hash": actual_hash,
                "expected_hash": expected_hash_lower
            }
            
        except Exception as e:
            logger.error(f"Error calculating hash: {e}")
            return {
                "valid": False,
                "message": f"Error calculating hash: {str(e)}",
                "actual_hash": None
            }


@app.get("/")
async def root() -> Dict[str, str]:
    """Корневой эндпоинт"""
    return {
        "service": "File Upload Service",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Проверка здоровья сервиса"""
    return {"status": "healthy"}


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(..., description="File to upload"),
    expected_hash: str = Form(..., description="Expected SHA-256 hash of the file"),
    file_type: Optional[str] = Form(None, description="Type of the file (e.g., 'distribution', 'config')")
) -> Dict[str, Any]:
    """
    Загрузка файла с проверкой контрольной суммы
    
    Args:
        file: Загружаемый файл
        expected_hash: Ожидаемый SHA-256 хеш
        file_type: Опциональный тип файла
        
    Returns:
        Результат загрузки и проверки
    """
    logger.info(f"Starting upload for file: {file.filename}")
    
    try:
        # Проверяем наличие файла
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided"
            )
        
        # Проверяем формат хеша
        if not expected_hash or len(expected_hash) != 64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid SHA-256 hash format (should be 64 hex characters)"
            )
        
        # Сохраняем файл
        uploads_dir = service_state["uploads_dir"]
        saved_file_path = await FileUploadService.save_uploaded_file(
            file,
            uploads_dir
        )
        
        # Проверяем хеш файла
        hash_validation = FileUploadService.validate_file_hash(
            saved_file_path,
            expected_hash
        )
        
        # Формируем ответ
        response_data = {
            "filename": file.filename,
            "file_size": saved_file_path.stat().st_size,
            "saved_path": str(saved_file_path),
            "upload_success": True,
            "hash_validation": hash_validation,
            "file_type": file_type,
            "timestamp": saved_file_path.stat().st_mtime
        }
        
        # Если хеш не совпал, возвращаем ошибку, но файл остается сохраненным
        if not hash_validation["valid"]:
            logger.warning(f"Hash mismatch for file: {file.filename}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    **response_data,
                    "message": "File uploaded but hash verification failed"
                }
            )
        
        logger.info(f"File uploaded and verified successfully: {file.filename}")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/verify/{filename}")
async def verify_file_hash(filename: str) -> Dict[str, Any]:
    """
    Проверка хеша уже загруженного файла
    
    Args:
        filename: Имя файла для проверки
        
    Returns:
        Результат проверки хеша
    """
    uploads_dir = service_state["uploads_dir"]
    file_path = uploads_dir / filename
    
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {filename}"
        )
    
    # Поскольку мы не знаем ожидаемый хеш, просто возвращаем вычисленный
    actual_hash = FileUploadService.calculate_file_hash(file_path)
    
    return {
        "filename": filename,
        "file_size": file_path.stat().st_size,
        "sha256_hash": actual_hash,
        "verification_time": file_path.stat().st_mtime
    }


@app.get("/files")
async def list_uploaded_files() -> Dict[str, Any]:
    """Список загруженных файлов"""
    uploads_dir = service_state["uploads_dir"]
    
    files = []
    for file_path in uploads_dir.iterdir():
        if file_path.is_file():
            stat = file_path.stat()
            files.append({
                "name": file_path.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "path": str(file_path)
            })
    
    return {
        "upload_directory": str(uploads_dir),
        "file_count": len(files),
        "files": files
    }


@app.delete("/files/{filename}")
async def delete_file(filename: str) -> Dict[str, Any]:
    """Удаление загруженного файла"""
    uploads_dir = service_state["uploads_dir"]
    file_path = uploads_dir / filename
    
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {filename}"
        )
    
    try:
        file_size = file_path.stat().st_size
        file_path.unlink()
        
        logger.info(f"File deleted: {filename}")
        
        return {
            "deleted": True,
            "filename": filename,
            "size": file_size,
            "message": "File successfully deleted"
        }
        
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting file: {str(e)}"
        )


# Пример клиента для тестирования
import aiohttp
import asyncio


async def test_upload() -> None:
    """Тестирование загрузки файла"""
    
    # Создаем тестовый файл
    test_content = b"This is a test distribution file content for SHA-256 hashing"
    expected_hash = hashlib.sha256(test_content).hexdigest()
    
    # Сохраняем тестовый файл
    test_file = Path("test_distribution.txt")
    test_file.write_bytes(test_content)
    
    try:
        # Загружаем файл через API
        url = "http://localhost:8000/upload"
        
        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field("expected_hash", expected_hash)
            form_data.add_field("file_type", "distribution")
            
            with open(test_file, "rb") as f:
                form_data.add_field(
                    "file",
                    f,
                    filename="test_distribution.txt",
                    content_type="text/plain"
                )
            
            async with session.post(url, data=form_data) as response:
                result = await response.json()
                print("Upload result:", result)
                
    finally:
        # Удаляем тестовый файл
        if test_file.exists():
            test_file.unlink()


if __name__ == "__main__":
    import uvicorn
    
    # Для запуска сервера используйте:
    # uvicorn upload_service:app --host 0.0.0.0 --port 8000 --reload
    
    # Для тестирования (требует запущенного сервера):
    # asyncio.run(test_upload())
    
    print("File Upload Service")
    print("To start the server, run:")
    print("uvicorn upload_service:app --host 0.0.0.0 --port 8000 --reload")