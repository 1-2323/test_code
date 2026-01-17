import os
import hashlib
import requests
import zipfile
import shutil
import logging
from pathlib import Path
from typing import Optional

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("AutoUpdater")

class SoftwareUpdater:
    """
    Клиент для загрузки, проверки и установки обновлений ПО.
    """

    def __init__(self, working_dir: str, temp_dir: str = "update_temp"):
        self.working_dir = Path(working_dir)
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(exist_ok=True)

    def _calculate_sha256(self, file_path: Path) -> str:
        """Вычисляет SHA-256 хеш файла для проверки целостности."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def download_update(self, url: str, destination: Path):
        """Скачивает файл архива с сервера."""
        logger.info(f"Загрузка обновления из {url}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info("Загрузка завершена.")

    def apply_update(self, archive_name: str, expected_hash: str, update_url: str) -> bool:
        """
        Полный цикл обновления:
        1. Загрузка
        2. Проверка хеша
        3. Распаковка
        """
        archive_path = self.temp_dir / archive_name

        try:
            # 1. Загрузка
            self.download_update(update_url, archive_path)

            # 2. Проверка целостности
            logger.info("Проверка контрольной суммы...")
            actual_hash = self._calculate_sha256(archive_path)
            
            if actual_hash.lower() != expected_hash.lower():
                logger.error(f"Ошибка целостности! Ожидалось: {expected_hash}, получено: {actual_hash}")
                return False
            
            logger.info("Контрольная сумма совпадает.")

            # 3. Распаковка в рабочую директорию
            logger.info(f"Распаковка в {self.working_dir}...")
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # В продакшене здесь стоит добавить бэкап старой версии
                zip_ref.extractall(self.working_dir)

            logger.info("Обновление успешно установлено.")
            return True

        except Exception as e:
            logger.error(f"Критическая ошибка при обновлении: {e}")
            return False
        finally:
            # Очистка временных файлов
            if archive_path.exists():
                os.remove(archive_path)

# --- Пример использования ---

if __name__ == "__main__":
    # Параметры обновления (обычно приходят из API запроса 'check_updates')
    UPDATE_CONFIG = {
        "url": "https://server.com/releases/v2.0.0.zip",
        "filename": "v2.0.0.zip",
        "sha256": "5d41402abc4b2a76b9719d911017c592" # Пример хеша
    }

    updater = SoftwareUpdater(working_dir="./my_app_files")
    
    # Запуск процесса (в данном примере URL демонстрационный)
    # success = updater.apply_update(
    #     archive_name=UPDATE_CONFIG["filename"],
    #     expected_hash=UPDATE_CONFIG["sha256"],
    #     update_url=UPDATE_CONFIG["url"]
    # )
    
    print("Клиент обновления инициализирован. Ожидание команды...")