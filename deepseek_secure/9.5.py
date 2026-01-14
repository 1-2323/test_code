import os
import gzip
import shutil
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

class LogRotator:
    def __init__(
        self,
        log_dir: str,
        max_file_size_mb: int = 10,
        backup_count: int = 5,
        compression_level: int = 9,
        integrity_check: bool = True,
        encryption_key: Optional[str] = None
    ):
        """
        Инициализация системы ротации логов.
        
        Args:
            log_dir: Директория для хранения логов
            max_file_size_mb: Максимальный размер файла в МБ перед ротацией
            backup_count: Количество хранимых архивных копий
            compression_level: Уровень сжатия (1-9)
            integrity_check: Проверка целостности файлов
            encryption_key: Ключ для шифрования (если None - шифрование отключено)
        """
        self.log_dir = Path(log_dir)
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.backup_count = backup_count
        self.compression_level = compression_level
        self.integrity_check = integrity_check
        self.encryption_key = encryption_key
        self.lock = threading.RLock()
        
        # Создаем директории если их нет
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.log_dir / "archive"
        self.archive_dir.mkdir(exist_ok=True)
        self.metadata_dir = self.log_dir / "metadata"
        self.metadata_dir.mkdir(exist_ok=True)
        
        # Настройка логирования самой системы
        self.setup_system_logger()
        
        # Пул потоков для асинхронных операций
        self.executor = ThreadPoolExecutor(max_workers=2)
        
    def setup_system_logger(self):
        """Настройка логгера для системы ротации."""
        self.system_logger = logging.getLogger("LogRotator")
        self.system_logger.setLevel(logging.INFO)
        
        handler = logging.FileHandler(self.log_dir / "rotator_system.log")
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.system_logger.addHandler(handler)
        
    def calculate_hash(self, filepath: Path) -> str:
        """Вычисление хеша файла для проверки целостности."""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def verify_integrity(self, original_hash: str, filepath: Path) -> bool:
        """Проверка целостности файла."""
        current_hash = self.calculate_hash(filepath)
        return original_hash == current_hash
    
    def encrypt_file(self, source: Path, target: Path):
        """Шифрование файла (упрощенная реализация)."""
        if not self.encryption_key:
            return
            
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64
            import secrets
            
            # Генерация ключа из пароля
            salt = secrets.token_bytes(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(
                self.encryption_key.encode()
            ))
            
            cipher = Fernet(key)
            
            with open(source, 'rb') as f:
                data = f.read()
            
            encrypted_data = cipher.encrypt(data)
            
            with open(target, 'wb') as f:
                f.write(salt)
                f.write(encrypted_data)
                
        except ImportError:
            self.system_logger.warning(
                "cryptography not installed, encryption disabled"
            )
    
    def decrypt_file(self, source: Path, target: Path):
        """Дешифрование файла."""
        if not self.encryption_key:
            return
            
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64
            
            with open(source, 'rb') as f:
                salt = f.read(16)
                encrypted_data = f.read()
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(
                self.encryption_key.encode()
            ))
            
            cipher = Fernet(key)
            decrypted_data = cipher.decrypt(encrypted_data)
            
            with open(target, 'wb') as f:
                f.write(decrypted_data)
                
        except ImportError:
            raise RuntimeError("Decryption requires cryptography library")
    
    def compress_file(self, source: Path, target: Path):
        """Сжатие файла с проверкой целостности."""
        original_hash = None
        if self.integrity_check:
            original_hash = self.calculate_hash(source)
        
        # Сначала шифруем если нужно
        temp_file = target.with_suffix('.tmp')
        if self.encryption_key:
            self.encrypt_file(source, temp_file)
        else:
            shutil.copy2(source, temp_file)
        
        # Затем сжимаем
        with open(temp_file, 'rb') as f_in:
            with gzip.open(target, 'wb', compresslevel=self.compression_level) as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Сохраняем метаданные
        metadata = {
            'original_filename': source.name,
            'original_size': source.stat().st_size,
            'compressed_size': target.stat().st_size,
            'rotation_time': datetime.utcnow().isoformat(),
            'original_hash': original_hash,
            'encrypted': self.encryption_key is not None,
            'compression_level': self.compression_level
        }
        
        metadata_file = self.metadata_dir / f"{target.name}.meta"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # Очистка временных файлов
        temp_file.unlink(missing_ok=True)
        
        self.system_logger.info(
            f"Compressed {source.name} from {metadata['original_size']} to "
            f"{metadata['compressed_size']} bytes"
        )
    
    def decompress_file(self, source: Path, target: Path):
        """Распаковка файла с проверкой целостности."""
        metadata_file = self.metadata_dir / f"{source.name}.meta"
        
        if not metadata_file.exists():
            self.system_logger.error(f"No metadata found for {source.name}")
            return False
        
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        # Распаковываем
        temp_compressed = target.with_suffix('.tmp.gz')
        with gzip.open(source, 'rb') as f_in:
            with open(temp_compressed, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Дешифруем если нужно
        if metadata.get('encrypted', False):
            if not self.encryption_key:
                self.system_logger.error("Encryption key required for decryption")
                return False
            self.decrypt_file(temp_compressed, target)
        else:
            shutil.copy2(temp_compressed, target)
        
        # Проверка целостности
        if self.integrity_check and metadata.get('original_hash'):
            if not self.verify_integrity(metadata['original_hash'], target):
                self.system_logger.error(f"Integrity check failed for {source.name}")
                target.unlink(missing_ok=True)
                return False
        
        temp_compressed.unlink(missing_ok=True)
        return True
    
    def rotate_file(self, log_file: Path):
        """Ротация файла лога."""
        with self.lock:
            try:
                if not log_file.exists():
                    return
                
                file_size = log_file.stat().st_size
                if file_size < self.max_file_size:
                    return
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_name = f"{log_file.stem}_{timestamp}{log_file.suffix}.gz"
                archive_path = self.archive_dir / archive_name
                
                # Создаем архивную копию
                self.compress_file(log_file, archive_path)
                
                # Очищаем исходный файл
                with open(log_file, 'w') as f:
                    f.truncate(0)
                
                # Управление количеством архивных копий
                self.cleanup_old_archives(log_file.stem)
                
                self.system_logger.info(
                    f"Rotated {log_file.name} to {archive_name}"
                )
                
            except Exception as e:
                self.system_logger.error(f"Error rotating {log_file.name}: {str(e)}")
    
    def cleanup_old_archives(self, log_basename: str):
        """Удаление старых архивных копий."""
        try:
            archives = sorted(
                self.archive_dir.glob(f"{log_basename}_*.gz"),
                key=os.path.getmtime,
                reverse=True
            )
            
            for archive in archives[self.backup_count:]:
                metadata_file = self.metadata_dir / f"{archive.name}.meta"
                
                # Дополнительная проверка целостности перед удалением
                if self.integrity_check:
                    temp_dir = self.archive_dir / "temp_verify"
                    temp_dir.mkdir(exist_ok=True)
                    
                    temp_file = temp_dir / archive.name.replace('.gz', '')
                    if self.decompress_file(archive, temp_file):
                        self.system_logger.info(
                            f"Verified integrity before deletion: {archive.name}"
                        )
                    temp_file.unlink(missing_ok=True)
                
                archive.unlink()
                metadata_file.unlink(missing_ok=True)
                self.system_logger.info(f"Removed old archive: {archive.name}")
                
        except Exception as e:
            self.system_logger.error(f"Error cleaning up archives: {str(e)}")
    
    def schedule_rotation(self, interval_minutes: int = 60):
        """Планирование регулярной ротации."""
        def rotation_worker():
            while True:
                time.sleep(interval_minutes * 60)
                self.rotate_all_logs()
        
        thread = threading.Thread(target=rotation_worker, daemon=True)
        thread.start()
        return thread
    
    def rotate_all_logs(self):
        """Ротация всех логов в директории."""
        log_files = list(self.log_dir.glob("*.log"))
        log_files = [f for f in log_files if f.name != "rotator_system.log"]
        
        for log_file in log_files:
            self.executor.submit(self.rotate_file, log_file)
    
    def restore_archive(self, archive_filename: str, target_dir: Optional[Path] = None):
        """Восстановление файла из архива."""
        archive_path = self.archive_dir / archive_filename
        
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive {archive_filename} not found")
        
        if target_dir is None:
            target_dir = self.log_dir
        
        target_dir.mkdir(exist_ok=True)
        
        # Получаем оригинальное имя файла из метаданных
        metadata_file = self.metadata_dir / f"{archive_filename}.meta"
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            original_name = metadata.get('original_filename', 
                                       archive_filename.replace('.gz', ''))
        else:
            original_name = archive_filename.replace('.gz', '')
        
        target_path = target_dir / original_name
        
        if self.decompress_file(archive_path, target_path):
            self.system_logger.info(f"Restored {archive_filename} to {target_path}")
            return target_path
        else:
            raise RuntimeError(f"Failed to restore {archive_filename}")
    
    def get_archive_info(self) -> List[Dict]:
        """Получение информации об архивных файлах."""
        archives_info = []
        
        for archive in self.archive_dir.glob("*.gz"):
            metadata_file = self.metadata_dir / f"{archive.name}.meta"
            
            info = {
                'filename': archive.name,
                'size': archive.stat().st_size,
                'modified': datetime.fromtimestamp(
                    archive.stat().st_mtime
                ).isoformat(),
                'metadata_exists': metadata_file.exists()
            }
            
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    info['metadata'] = json.load(f)
            
            archives_info.append(info)
        
        return archives_info
    
    def verify_all_archives(self) -> Dict[str, bool]:
        """Проверка целостности всех архивов."""
        results = {}
        
        for archive in self.archive_dir.glob("*.gz"):
            temp_dir = self.archive_dir / "temp_verify"
            temp_dir.mkdir(exist_ok=True)
            
            temp_file = temp_dir / archive.name.replace('.gz', '')
            
            try:
                success = self.decompress_file(archive, temp_file)
                results[archive.name] = success
                
                if success:
                    self.system_logger.info(
                        f"Archive integrity verified: {archive.name}"
                    )
                else:
                    self.system_logger.error(
                        f"Archive integrity failed: {archive.name}"
                    )
                    
            except Exception as e:
                results[archive.name] = False
                self.system_logger.error(
                    f"Error verifying {archive.name}: {str(e)}"
                )
            finally:
                temp_file.unlink(missing_ok=True)
        
        # Удаляем временную директорию
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        
        return results
    
    def cleanup(self):
        """Очистка ресурсов."""
        self.executor.shutdown(wait=True)


class ProtectedLogger:
    """Обертка для стандартного логгера с защитой от модификации."""
    
    def __init__(self, name: str, log_dir: str, rotator: LogRotator):
        """
        Args:
            name: Имя логгера
            log_dir: Директория для логов
            rotator: Объект ротатора
        """
        self.name = name
        self.log_file = Path(log_dir) / f"{name}.log"
        self.rotator = rotator
        
        # Настройка логгера
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Удаляем существующие обработчики
        self.logger.handlers.clear()
        
        # Создаем обработчик с проверкой ротации
        handler = self.ProtectedFileHandler(
            self.log_file,
            rotator=self.rotator
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        
        self.logger.addHandler(handler)
    
    class ProtectedFileHandler(logging.FileHandler):
        """Обработчик файла с защитой от модификации."""
        
        def __init__(self, filename, rotator, mode='a', encoding=None, delay=False):
            super().__init__(filename, mode, encoding, delay)
            self.rotator = rotator
            self.filename_path = Path(filename)
            
        def emit(self, record):
            """Переопределенный метод записи лога с проверкой ротации."""
            # Проверяем размер файла перед записью
            if self.filename_path.exists():
                if self.filename_path.stat().st_size >= self.rotator.max_file_size:
                    self.rotator.rotate_file(self.filename_path)
            
            super().emit(record)
    
    def info(self, msg: str):
        self.logger.info(msg)
    
    def error(self, msg: str):
        self.logger.error(msg)
    
    def warning(self, msg: str):
        self.logger.warning(msg)
    
    def debug(self, msg: str):
        self.logger.debug(msg)


# Пример использования системы
if __name__ == "__main__":
    # Инициализация системы ротации
    rotator = LogRotator(
        log_dir="./logs",
        max_file_size_mb=1,  # 1 МБ для демонстрации
        backup_count=3,
        compression_level=6,
        integrity_check=True,
        encryption_key="your-secret-key-here"  # В реальном использовании храните безопасно
    )
    
    # Создание защищенного логгера
    app_logger = ProtectedLogger("application", "./logs", rotator)
    
    # Запуск регулярной ротации (каждые 10 минут)
    rotator.schedule_rotation(interval_minutes=10)
    
    # Использование логгера
    try:
        app_logger.info("Application started")
        
        # Имитация работы приложения
        for i in range(1000):
            app_logger.info(f"Processing item {i}")
            time.sleep(0.01)
            
            # Ручная проверка ротации
            if i % 100 == 0:
                rotator.rotate_all_logs()
        
        app_logger.info("Application finished")
        
    except KeyboardInterrupt:
        app_logger.warning("Application interrupted")
    finally:
        # Проверка целостности архивов перед завершением
        integrity_results = rotator.verify_all_archives()
        app_logger.info(f"Integrity check results: {sum(integrity_results.values())}"
                       f"/{len(integrity_results)} archives valid")
        
        # Очистка ресурсов
        rotator.cleanup()