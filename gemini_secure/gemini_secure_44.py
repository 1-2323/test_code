import os
import shutil
import gzip
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

# --- Настройки ---
LOG_DIR: Final[Path] = Path("/var/log/myapp")
ARCHIVE_DIR: Final[Path] = Path("/var/log/myapp/archive")
RETENTION_DAYS: Final[int] = 7
DISK_THRESHOLD_GB: Final[int] = 5  # Минимально допустимое место на диске

# Настройка внутреннего лога скрипта
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LogRotator")

class LogRotator:
    """Система ротации, сжатия и контроля дискового пространства."""

    def __init__(self):
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    def check_disk_space(self) -> bool:
        """Проверяет наличие свободного места перед архивацией."""
        total, used, free = shutil.disk_usage(LOG_DIR)
        free_gb = free // (2**30)
        
        if free_gb < DISK_THRESHOLD_GB:
            logger.critical(f"LOW DISK SPACE: Only {free_gb}GB left. Aborting rotation to prevent crash.")
            self._send_alert(f"Disk space critical: {free_gb}GB remaining.")
            return False
        return True

    def _send_alert(self, message: str):
        """Заглушка для отправки уведомлений (Email/Slack/Telegram)."""
        logger.error(f"ALERT SENT: {message}")

    def archive_logs(self):
        """Перемещает и сжимает логи, созданные более 24 часов назад."""
        if not self.check_disk_space():
            return

        # Определяем дату вчерашнего дня для именования
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Ищем файлы логов (например, *.log), исключая уже сжатые
        for log_file in LOG_DIR.glob("*.log"):
            if log_file.is_dir():
                continue

            archive_name = ARCHIVE_DIR / f"{log_file.stem}_{yesterday_str}.gz"
            
            try:
                # 1. Сжатие файла
                with open(log_file, 'rb') as f_in:
                    with gzip.open(archive_name, 'wb', compresslevel=9) as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # 2. Проверка успешности (существование и размер > 0)
                if archive_name.exists() and archive_name.stat().st_size > 0:
                    logger.info(f"Successfully archived: {log_file.name} -> {archive_name.name}")
                    # 3. Безопасное удаление оригинала
                    log_file.unlink()
                else:
                    raise IOError("Archive verification failed.")

            except Exception as e:
                logger.error(f"Failed to archive {log_file.name}: {e}")
                if archive_name.exists():
                    archive_name.unlink() # Удаляем битый архив

    def cleanup_old_archives(self):
        """Удаляет архивы старше срока хранения (RETENTION_DAYS)."""
        cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)
        
        for archive in ARCHIVE_DIR.glob("*.gz"):
            file_time = datetime.fromtimestamp(archive.stat().st_mtime)
            if file_time < cutoff_date:
                archive.unlink()
                logger.info(f"Deleted old archive: {archive.name}")

# --- Запуск ---
if __name__ == "__main__":
    rotator = LogRotator()
    rotator.archive_logs()
    rotator.cleanup_old_archives()