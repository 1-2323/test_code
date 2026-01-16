"""
Сервис для управления загрузкой файлов с проверкой существования в реестре БД.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod
import sqlite3


@dataclass
class FileMetadata:
    """Модель метаданных файла из базы данных."""
    id: int
    filename: str
    file_path: str
    file_size: int
    mime_type: str
    created_at: str


class DatabaseRegistry(ABC):
    """Абстрактный класс для работы с реестром файлов в БД."""
    
    @abstractmethod
    def check_file_exists(self, filename: str) -> Optional[FileMetadata]:
        """Проверяет существование файла в реестре."""
        pass


class SQLiteRegistry(DatabaseRegistry):
    """Реализация реестра на SQLite."""
    
    def __init__(self, db_path: str = "file_registry.db"):
        """
        Инициализация подключения к БД.
        
        Args:
            db_path: Путь к файлу базы данных SQLite.
        """
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self) -> None:
        """Инициализирует таблицу файлов, если она не существует."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL UNIQUE,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    mime_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
    
    def check_file_exists(self, filename: str) -> Optional[FileMetadata]:
        """
        Проверяет наличие файла в реестре БД.
        
        Args:
            filename: Имя файла для поиска.
            
        Returns:
            FileMetadata если файл найден, None если не найден.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM files WHERE filename = ?",
                    (filename,)
                )
                row = cursor.fetchone()
                
                if row:
                    return FileMetadata(
                        id=row['id'],
                        filename=row['filename'],
                        file_path=row['file_path'],
                        file_size=row['file_size'],
                        mime_type=row['mime_type'],
                        created_at=row['created_at']
                    )
                return None
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при запросе к БД: {str(e)}")


class FileStorage:
    """Класс для работы с локальным хранилищем файлов."""
    
    def __init__(self, storage_path: str = "./documents"):
        """
        Инициализация хранилища файлов.
        
        Args:
            storage_path: Путь к директории с файлами.
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def get_file_content(self, filename: str) -> bytes:
        """
        Читает содержимое файла из локального хранилища.
        
        Args:
            filename: Имя файла для чтения.
            
        Returns:
            Байтовое содержимое файла.
            
        Raises:
            FileNotFoundError: Если файл не существует.
            IOError: Если произошла ошибка при чтении файла.
        """
        file_path = self.storage_path / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"Файл не найден: {filename}")
        
        if not file_path.is_file():
            raise ValueError(f"Путь не является файлом: {filename}")
        
        try:
            return file_path.read_bytes()
        except IOError as e:
            raise IOError(f"Ошибка при чтении файла {filename}: {str(e)}")


class DatabaseError(Exception):
    """Кастомное исключение для ошибок базы данных."""
    pass


class FileDownloadError(Exception):
    """Кастомное исключение для ошибок загрузки файла."""
    pass


class FileDownloadManager:
    """
    Основной сервис для управления загрузкой файлов.
    Объединяет проверку в реестре БД и чтение из локального хранилища.
    """
    
    def __init__(
        self,
        registry: DatabaseRegistry,
        storage: FileStorage
    ):
        """
        Инициализация менеджера загрузки файлов.
        
        Args:
            registry: Реализация интерфейса DatabaseRegistry.
            storage: Объект для работы с локальным хранилищем.
        """
        self.registry = registry
        self.storage = storage
    
    def download_file(self, filename: str) -> Dict[str, Any]:
        """
        Основной метод для загрузки файла.
        
        Args:
            filename: Имя файла для загрузки.
            
        Returns:
            Словарь с метаданными и содержимым файла.
            
        Raises:
            FileDownloadError: Если файл не найден в реестре или хранилище.
        """
        try:
            # Шаг 1: Проверка существования файла в реестре БД
            file_metadata = self.registry.check_file_exists(filename)
            
            if not file_metadata:
                raise FileDownloadError(
                    f"Файл '{filename}' не найден в реестре базы данных"
                )
            
            # Шаг 2: Получение содержимого файла из локального хранилища
            file_content = self.storage.get_file_content(filename)
            
            # Шаг 3: Формирование ответа
            return {
                "success": True,
                "metadata": {
                    "filename": file_metadata.filename,
                    "file_size": file_metadata.file_size,
                    "mime_type": file_metadata.mime_type,
                    "created_at": file_metadata.created_at
                },
                "content": file_content,
                "message": f"Файл '{filename}' успешно загружен"
            }
            
        except FileNotFoundError as e:
            raise FileDownloadError(
                f"Файл '{filename}' не найден в локальном хранилище: {str(e)}"
            )
        except (DatabaseError, IOError) as e:
            raise FileDownloadError(
                f"Ошибка при загрузке файла '{filename}': {str(e)}"
            )
    
    def download_file_safe(self, filename: str) -> Dict[str, Any]:
        """
        Безопасная версия метода download_file с обработкой всех исключений.
        
        Args:
            filename: Имя файла для загрузки.
            
        Returns:
            Словарь с результатом операции (успех/ошибка).
        """
        try:
            return self.download_file(filename)
        except FileDownloadError as e:
            return {
                "success": False,
                "error": str(e),
                "metadata": None,
                "content": None
            }


# Пример использования
if __name__ == "__main__":
    # Инициализация компонентов
    registry = SQLiteRegistry()
    storage = FileStorage("./documents")
    download_manager = FileDownloadManager(registry, storage)
    
    # Пример загрузки файла
    try:
        result = download_manager.download_file("example.pdf")
        print(f"Файл загружен: {result['message']}")
        print(f"Размер файла: {result['metadata']['file_size']} байт")
    except FileDownloadError as e:
        print(f"Ошибка: {e}")
    
    # Пример безопасной загрузки
    result = download_manager.download_file_safe("unknown.txt")
    if not result["success"]:
        print(f"Ошибка при безопасной загрузке: {result['error']}")