import os
import tarfile
import shutil
import logging
import psutil
from datetime import datetime, timedelta
from pathlib import Path

# Настройка системного лога для самого скрипта
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LogRotator")

class LogArchiver:
    """
    Система автоматической ротации, сжатия и контроля места на диске.
    """

    def __init__(self, log_dir: str, archive_dir: str, disk_threshold_pct: float = 90.0):
        self.log_dir = Path(log_dir)
        self.archive_dir = Path(archive_dir)
        self.threshold = disk_threshold_pct
        
        # Создаем папку архива, если её нет
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def check_disk_space(self):
        """Проверяет свободное место на диске."""
        disk_usage = psutil.disk_usage(self.log_dir.anchor)
        if disk_usage.percent > self.threshold:
            msg = f"ВНИМАНИЕ: Диск заполнен на {disk_usage.percent}%! Порог: {self.threshold}%"
            logger.warning(msg)
            # Здесь можно вызвать функцию отправки в Telegram/Email
            return False
        logger.info(f"Свободное место в норме: {100 - disk_usage.percent:.1f}% свободно.")
        return True

    def rotate_logs(self, days_old: int = 1):
        """
        Находит логи старше определенного количества дней, 
        сжимает их и перемещает в архив.
        """
        cutoff_date = datetime.now() - timedelta(days=days_old)
        archived_count = 0

        # Ищем файлы с расширением .log
        for log_file in self.log_dir.glob("*.log"):
            file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)

            if file_mtime < cutoff_date:
                archive_name = f"logs_{file_mtime.strftime('%Y-%m-%d')}.tar.gz"
                archive_path = self.archive_dir / archive_name

                logger.info(f"Архивация: {log_file.name} -> {archive_name}")
                
                try:
                    # Создание сжатого архива
                    with tarfile.open(archive_path, "w:gz") as tar:
                        tar.add(log_file, arcname=log_file.name)
                    
                    # Удаление оригинального файла после успешного сжатия
                    log_file.unlink()
                    archived_count += 1
                except Exception as e:
                    logger.error(f"Ошибка при обработке {log_file.name}: {e}")

        logger.info(f"Ротация завершена. Архивов создано: {archived_count}")

# --- Запуск задачи ---

if __name__ == "__main__":
    # Настройки путей
    LOG_PATH = "./logs"
    ARCHIVE_PATH = "./logs/archives"

    # Создадим тестовый файл, если папка пуста
    os.makedirs(LOG_PATH, exist_ok=True)
    
    archiver = LogArchiver(
        log_dir=LOG_PATH, 
        archive_dir=ARCHIVE_PATH, 
        disk_threshold_pct=85.0
    )

    # 1. Проверка места
    archiver.check_disk_space()

    # 2. Ротация файлов старше 1 дня
    archiver.rotate_logs(days_old=1)