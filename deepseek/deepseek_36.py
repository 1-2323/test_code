import os
import hashlib
import tarfile
import zipfile
import tempfile
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse
import logging
from dataclasses import dataclass

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    """Результат операции обновления"""
    success: bool
    message: str
    version: Optional[str] = None
    extracted_to: Optional[Path] = None


class UpdateClient:
    """Клиент для автоматического обновления программного обеспечения"""
    
    def __init__(
        self,
        download_url: str,
        target_dir: Union[str, Path],
        expected_checksum: str,
        version: str
    ) -> None:
        """
        Инициализация клиента обновления
        
        Args:
            download_url: URL для скачивания архива с обновлением
            target_dir: Целевая директория для распаковки
            expected_checksum: Ожидаемая контрольная сумма (SHA-256)
            version: Версия обновления
        """
        self.download_url = download_url
        self.target_dir = Path(target_dir)
        self.expected_checksum = expected_checksum.lower()
        self.version = version
        
        # Создаем целевую директорию если её нет
        self.target_dir.mkdir(parents=True, exist_ok=True)
    
    def calculate_checksum(self, file_path: Path, algorithm: str = "sha256") -> str:
        """
        Вычисление контрольной суммы файла
        
        Args:
            file_path: Путь к файлу
            algorithm: Алгоритм хеширования (по умолчанию SHA-256)
            
        Returns:
            Контрольная сумма в виде hex строки
        """
        hash_func = hashlib.new(algorithm)
        
        with open(file_path, "rb") as f:
            # Читаем файл блоками для эффективности с большими файлами
            for chunk in iter(lambda: f.read(4096), b""):
                hash_func.update(chunk)
        
        return hash_func.hexdigest()
    
    def download_file(self, url: str, destination: Path) -> bool:
        """
        Скачивание файла по URL
        
        Args:
            url: URL для скачивания
            destination: Путь для сохранения файла
            
        Returns:
            True если скачивание успешно, иначе False
        """
        try:
            logger.info(f"Downloading update from {url}")
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"File downloaded successfully: {destination}")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Download failed: {e}")
            return False
    
    def extract_archive(self, archive_path: Path, extract_to: Path) -> bool:
        """
        Распаковка архива
        
        Args:
            archive_path: Путь к архиву
            extract_to: Целевая директория для распаковки
            
        Returns:
            True если распаковка успешна, иначе False
        """
        try:
            # Определяем тип архива по расширению
            suffix = archive_path.suffix.lower()
            
            if suffix == ".zip":
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(extract_to)
                logger.info(f"ZIP archive extracted to {extract_to}")
                
            elif suffix in [".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2"]:
                mode = "r"
                if suffix in [".tar.gz", ".tgz"]:
                    mode = "r:gz"
                elif suffix in [".tar.bz2", ".tbz2"]:
                    mode = "r:bz2"
                
                with tarfile.open(archive_path, mode) as tar_ref:
                    tar_ref.extractall(extract_to)
                logger.info(f"TAR archive extracted to {extract_to}")
                
            else:
                logger.error(f"Unsupported archive format: {suffix}")
                return False
            
            return True
            
        except (zipfile.BadZipFile, tarfile.TarError, OSError) as e:
            logger.error(f"Archive extraction failed: {e}")
            return False
    
    def perform_update(self) -> UpdateResult:
        """
        Выполнение полного цикла обновления
        
        Returns:
            Результат операции обновления
        """
        # Создаем временную директорию для загрузки
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Получаем имя файла из URL
            parsed_url = urlparse(self.download_url)
            filename = Path(parsed_url.path).name or f"update_{self.version}.zip"
            archive_path = temp_path / filename
            
            # Шаг 1: Скачивание архива
            logger.info(f"Step 1: Downloading update version {self.version}")
            if not self.download_file(self.download_url, archive_path):
                return UpdateResult(
                    success=False,
                    message="Failed to download update archive",
                    version=self.version
                )
            
            # Шаг 2: Проверка контрольной суммы
            logger.info("Step 2: Verifying checksum")
            actual_checksum = self.calculate_checksum(archive_path)
            
            if actual_checksum != self.expected_checksum:
                logger.error(
                    f"Checksum mismatch. Expected: {self.expected_checksum}, "
                    f"Actual: {actual_checksum}"
                )
                return UpdateResult(
                    success=False,
                    message="Checksum verification failed",
                    version=self.version
                )
            
            logger.info("Checksum verified successfully")
            
            # Шаг 3: Распаковка архива
            logger.info(f"Step 3: Extracting archive to {self.target_dir}")
            if not self.extract_archive(archive_path, self.target_dir):
                return UpdateResult(
                    success=False,
                    message="Failed to extract archive",
                    version=self.version
                )
            
            # Шаг 4: Очистка (опционально)
            logger.info("Step 4: Cleanup temporary files")
            # Временная директория автоматически очищается при выходе из контекста
            
            return UpdateResult(
                success=True,
                message="Update completed successfully",
                version=self.version,
                extracted_to=self.target_dir
            )


# Пример использования
def example_usage() -> None:
    """Пример использования клиента обновления"""
    # Конфигурация обновления
    config = {
        "download_url": "https://example.com/updates/app_v1.2.3.zip",
        "target_dir": "/opt/myapp",
        "expected_checksum": "a1b2c3d4e5f67890123456789abcdef1234567890abcdef1234567890abcdef",
        "version": "1.2.3"
    }
    
    # Создаем клиент обновления
    client = UpdateClient(**config)
    
    # Выполняем обновление
    result = client.perform_update()
    
    if result.success:
        logger.info(f"Update to version {result.version} completed successfully!")
        logger.info(f"Files extracted to: {result.extracted_to}")
    else:
        logger.error(f"Update failed: {result.message}")


if __name__ == "__main__":
    # Пример запуска (закомментировано, так как требует реальных URL и контрольных сумм)
    # example_usage()
    logger.info("UpdateClient class is ready for use")