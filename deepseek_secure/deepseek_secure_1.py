import os
from pathlib import Path
from typing import Optional
import sqlite3
from contextlib import contextmanager

class FileDownloadManager:
    """Сервис для безопасной загрузки файлов из локального хранилища."""
    
    def __init__(self, db_path: str = "database.db", storage_path: str = "./documents/"):
        """
        Инициализация менеджера загрузки файлов.
        
        Args:
            db_path: Путь к файлу базы данных с реестром файлов
            storage_path: Путь к директории с файлами
        """
        self.db_path = db_path
        self.storage_path = Path(storage_path).resolve()
        
        # Создаем директорию, если она не существует
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def _get_db_connection(self):
        """Контекстный менеджер для подключения к БД."""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Очищает имя файла от потенциально опасных символов.
        
        Args:
            filename: Исходное имя файла
            
        Returns:
            Очищенное имя файла
            
        Raises:
            ValueError: Если имя файла содержит опасные последовательности
        """
        # Удаляем относительные пути и опасные символы
        clean_name = os.path.basename(filename)
        
        # Проверяем на попытку directory traversal
        if clean_name != filename:
            raise ValueError("Имя файла содержит недопустимые символы")
        
        # Дополнительные проверки
        if clean_name.startswith('.') or '..' in clean_name:
            raise ValueError("Имя файла содержит недопустимые паттерны")
            
        return clean_name
    
    def _check_file_in_registry(self, filename: str) -> bool:
        """
        Проверяет наличие файла в реестре БД.
        
        Args:
            filename: Имя файла для проверки
            
        Returns:
            True если файл существует в реестре
        """
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM file_registry WHERE filename = ?",
                (filename,)
            )
            return cursor.fetchone()[0] > 0
    
    def _get_safe_filepath(self, filename: str) -> Path:
        """
        Создает безопасный путь к файлу.
        
        Args:
            filename: Имя файла
            
        Returns:
            Абсолютный путь к файлу
            
        Raises:
            ValueError: Если путь выходит за пределы целевой директории
        """
        # Очищаем имя файла
        clean_filename = self._sanitize_filename(filename)
        
        # Собираем полный путь
        file_path = (self.storage_path / clean_filename).resolve()
        
        # Проверяем, что путь находится внутри целевой директории
        try:
            file_path.relative_to(self.storage_path)
        except ValueError:
            raise ValueError("Попытка доступа к файлу вне целевой директории")
        
        return file_path
    
    def download_file(self, filename: str) -> bytes:
        """
        Основной метод загрузки файла.
        
        Args:
            filename: Имя запрашиваемого файла
            
        Returns:
            Содержимое файла в виде байтов
            
        Raises:
            FileNotFoundError: Если файл не найден
            PermissionError: Если нет доступа к файлу
            ValueError: Если имя файла невалидно
        """
        try:
            # Проверяем наличие файла в реестре
            if not self._check_file_in_registry(filename):
                raise FileNotFoundError(f"Файл '{filename}' не найден в реестре")
            
            # Получаем безопасный путь
            file_path = self._get_safe_filepath(filename)
            
            # Проверяем существование файла
            if not file_path.exists():
                raise FileNotFoundError(f"Файл '{filename}' не существует в хранилище")
            
            # Читаем содержимое файла
            return file_path.read_bytes()
            
        except FileNotFoundError as e:
            # Логируем ошибку (в реальном приложении)
            print(f"FileNotFoundError: {e}")
            raise
        except PermissionError as e:
            print(f"PermissionError: {e}")
            raise
        except ValueError as e:
            print(f"ValueError: {e}")
            raise
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise

# Пример использования
if __name__ == "__main__":
    manager = FileDownloadManager()
    
    try:
        # Инициализируем тестовую БД (в реальном приложении будет отдельно)
        with sqlite3.connect("database.db") as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_registry (
                    id INTEGER PRIMARY KEY,
                    filename TEXT UNIQUE NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Тестовые данные
            cursor.execute("INSERT OR IGNORE INTO file_registry (filename) VALUES (?)", 
                          ("report.pdf",))
            conn.commit()
        
        # Создаем тестовый файл
        test_file = Path("./documents/report.pdf")
        test_file.parent.mkdir(exist_ok=True)
        test_file.write_text("Тестовое содержимое PDF")
        
        # Загружаем файл
        content = manager.download_file("report.pdf")
        print(f"Файл успешно загружен, размер: {len(content)} байт")
        
    except Exception as e:
        print(f"Ошибка: {e}")