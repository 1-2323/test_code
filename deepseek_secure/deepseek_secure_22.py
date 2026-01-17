from typing import Dict, Optional, Any, List, BinaryIO
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import os
import shutil
import hashlib
import mimetypes
from pathlib import Path
import sqlite3
from contextlib import contextmanager
import logging
import uuid

logger = logging.getLogger(__name__)


class FileType(str, Enum):
    """Типы файлов."""
    IMAGE = "image"
    DOCUMENT = "document"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    OTHER = "other"


@dataclass
class FileMetadata:
    """Метаданные файла."""
    filename: str
    size: int
    mime_type: str
    file_type: FileType
    hash: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    @classmethod
    def from_file(cls, file_path: Path) -> 'FileMetadata':
        """Создание метаданных из файла."""
        stat = file_path.stat()
        
        # Определяем MIME type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or 'application/octet-stream'
        
        # Определяем тип файла
        if mime_type.startswith('image/'):
            file_type = FileType.IMAGE
        elif mime_type.startswith('video/'):
            file_type = FileType.VIDEO
        elif mime_type.startswith('audio/'):
            file_type = FileType.AUDIO
        elif mime_type in ['application/pdf', 'application/msword', 
                          'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
            file_type = FileType.DOCUMENT
        elif mime_type in ['application/zip', 'application/x-rar-compressed']:
            file_type = FileType.ARCHIVE
        else:
            file_type = FileType.OTHER
        
        # Вычисляем хеш файла
        file_hash = cls._calculate_hash(file_path)
        
        return cls(
            filename=file_path.name,
            size=stat.st_size,
            mime_type=mime_type,
            file_type=file_type,
            hash=file_hash
        )
    
    @staticmethod
    def _calculate_hash(file_path: Path) -> str:
        """Вычисление SHA256 хеша файла."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256.update(chunk)
        return sha256.hexdigest()


@dataclass
class FileRecord:
    """Запись о файле в системе."""
    id: str
    user_id: str
    original_filename: str
    storage_path: str
    metadata: FileMetadata
    tags: List[str] = field(default_factory=list)
    is_public: bool = False
    description: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    accessed_at: datetime = field(default_factory=datetime.now)


class FileStorage:
    """Файловое хранилище."""
    
    def __init__(self, base_path: str = "./uploads", 
                 db_path: str = "files.db"):
        self.base_path = Path(base_path)
        self.db_path = db_path
        
        # Создаем базовые директории
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        self._init_database()
    
    def _init_database(self):
        """Инициализация БД."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    storage_path TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    duration REAL,
                    tags TEXT,
                    is_public BOOLEAN DEFAULT FALSE,
                    description TEXT,
                    created_at TIMESTAMP NOT NULL,
                    accessed_at TIMESTAMP NOT NULL,
                    downloads INTEGER DEFAULT 0
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON files(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_type ON files(file_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash ON files(hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_created ON files(created_at)")
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def save_file(self, user_id: str, file_obj: BinaryIO,
                  filename: str, tags: Optional[List[str]] = None,
                  description: Optional[str] = None,
                  is_public: bool = False) -> Optional[FileRecord]:
        """Сохранение файла в хранилище."""
        # Генерируем уникальный ID и путь
        file_id = str(uuid.uuid4())
        file_ext = Path(filename).suffix
        storage_filename = f"{file_id}{file_ext}"
        
        # Создаем структуру директорий по дате
        today = datetime.now()
        date_path = today.strftime("%Y/%m/%d")
        storage_path = self.base_path / date_path
        storage_path.mkdir(parents=True, exist_ok=True)
        
        full_path = storage_path / storage_filename
        
        try:
            # Сохраняем файл на диск
            with open(full_path, 'wb') as f:
                shutil.copyfileobj(file_obj, f)
            
            # Получаем метаданные
            metadata = FileMetadata.from_file(full_path)
            
            # Создаем запись в БД
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO files VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, (
                    file_id,
                    user_id,
                    filename,
                    str(full_path.relative_to(self.base_path)),
                    metadata.filename,
                    metadata.size,
                    metadata.mime_type,
                    metadata.file_type.value,
                    metadata.hash,
                    metadata.width,
                    metadata.height,
                    metadata.duration,
                    json.dumps(tags or []),
                    is_public,
                    description,
                    metadata.created_at.isoformat(),
                    metadata.created_at.isoformat(),
                    0  # downloads
                ))
                conn.commit()
            
            return FileRecord(
                id=file_id,
                user_id=user_id,
                original_filename=filename,
                storage_path=str(full_path.relative_to(self.base_path)),
                metadata=metadata,
                tags=tags or [],
                is_public=is_public,
                description=description
            )
            
        except Exception as e:
            logger.error(f"Error saving file: {e}")
            # Удаляем файл если запись в БД не удалась
            if full_path.exists():
                full_path.unlink()
            return None
    
    def get_file(self, file_id: str) -> Optional[FileRecord]:
        """Получение информации о файле."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM files WHERE id = ?",
                    (file_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    # Обновляем время последнего доступа
                    cursor.execute("""
                        UPDATE files 
                        SET accessed_at = ?, downloads = downloads + 1 
                        WHERE id = ?
                    """, (datetime.now().isoformat(), file_id))
                    conn.commit()
                    
                    return self._row_to_record(row)
        except Exception as e:
            logger.error(f"Error getting file: {e}")
        return None
    
    def get_file_path(self, file_id: str) -> Optional[Path]:
        """Получение пути к файлу."""
        record = self.get_file(file_id)
        if record:
            return self.base_path / record.storage_path
        return None
    
    def delete_file(self, file_id: str) -> bool:
        """Удаление файла."""
        try:
            # Получаем путь к файлу
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT storage_path FROM files WHERE id = ?",
                    (file_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    return False
                
                # Удаляем файл с диска
                file_path = self.base_path / row['storage_path']
                if file_path.exists():
                    file_path.unlink()
                
                # Удаляем запись из БД
                cursor.execute(
                    "DELETE FROM files WHERE id = ?",
                    (file_id,)
                )
                conn.commit()
                
                logger.info(f"File {file_id} deleted")
                return True
                
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False
    
    def search_files(self, user_id: Optional[str] = None,
                    file_type: Optional[FileType] = None,
                    tags: Optional[List[str]] = None,
                    limit: int = 100) -> List[FileRecord]:
        """Поиск файлов."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM files WHERE 1=1"
                params = []
                
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                
                if file_type:
                    query += " AND file_type = ?"
                    params.append(file_type.value)
                
                if tags:
                    for tag in tags:
                        query += f" AND tags LIKE ?"
                        params.append(f'%"{tag}"%')
                
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                
                records = []
                for row in cursor.fetchall():
                    records.append(self._row_to_record(row))
                
                return records
                
        except Exception as e:
            logger.error(f"Error searching files: {e}")
            return []
    
    def get_user_quota(self, user_id: str) -> Dict[str, Any]:
        """Получение квоты пользователя."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Общий размер файлов пользователя
                cursor.execute("""
                    SELECT COUNT(*) as file_count,
                           SUM(size) as total_size
                    FROM files 
                    WHERE user_id = ?
                """, (user_id,))
                
                row = cursor.fetchone()
                return {
                    'file_count': row['file_count'] or 0,
                    'total_size': row['total_size'] or 0
                }
                
        except Exception as e:
            logger.error(f"Error getting user quota: {e}")
            return {'file_count': 0, 'total_size': 0}
    
    def cleanup_old_files(self, days: int = 30) -> int:
        """Очистка старых файлов."""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Находим файлы для удаления
                cursor.execute("""
                    SELECT id, storage_path 
                    FROM files 
                    WHERE created_at < ?
                """, (cutoff_date.isoformat(),))
                
                deleted_count = 0
                for row in cursor.fetchall():
                    # Удаляем файл с диска
                    file_path = self.base_path / row['storage_path']
                    if file_path.exists():
                        file_path.unlink()
                    
                    # Удаляем запись из БД
                    cursor.execute(
                        "DELETE FROM files WHERE id = ?",
                        (row['id'],)
                    )
                    deleted_count += 1
                
                conn.commit()
                
                if deleted_count:
                    logger.info(f"Cleaned up {deleted_count} old files")
                
                return deleted_count
                
        except Exception as e:
            logger.error(f"Error cleaning up old files: {e}")
            return 0
    
    def _row_to_record(self, row) -> FileRecord:
        """Преобразование строки БД в FileRecord."""
        metadata = FileMetadata(
            filename=row['filename'],
            size=row['size'],
            mime_type=row['mime_type'],
            file_type=FileType(row['file_type']),
            hash=row['hash'],
            width=row['width'],
            height=row['height'],
            duration=row['duration'],
            created_at=datetime.fromisoformat(row['created_at'])
        )
        
        return FileRecord(
            id=row['id'],
            user_id=row['user_id'],
            original_filename=row['original_filename'],
            storage_path=row['storage_path'],
            metadata=metadata,
            tags=json.loads(row['tags']) if row['tags'] else [],
            is_public=bool(row['is_public']),
            description=row['description'],
            created_at=datetime.fromisoformat(row['created_at']),
            accessed_at=datetime.fromisoformat(row['accessed_at'])
        )