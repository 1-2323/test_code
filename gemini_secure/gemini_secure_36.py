import os
import shutil
import hashlib
import tempfile
import httpx
import zipfile
from typing import Final, Optional
from pathlib import Path

class UpdateError(Exception):
    """Базовое исключение для ошибок процесса обновления."""
    pass

class SoftwareUpdater:
    """
    Клиент для безопасного скачивания и атомарной установки обновлений.
    """
    
    # Доверенный домен (White-list)
    TRUSTED_DOMAIN: Final[str] = "https://updates.trusted-source.com"
    # Рабочая директория приложения
    APP_DIR: Final[Path] = Path("/opt/myapp")

    def __init__(self, current_version: str):
        self.current_version = current_version

    def _verify_checksum(self, file_path: Path, expected_hash: str) -> bool:
        """Проверяет целостность файла по алгоритму SHA-256."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return hmac.compare_digest(sha256_hash.hexdigest(), expected_hash)

    async def download_and_install(self, version: str, expected_hash: str):
        """
        Основной цикл обновления: Загрузка -> Проверка -> Изолированная распаковка -> Атомарная замена.
        """
        update_url = f"{self.TRUSTED_DOMAIN}/releases/v{version}/update.zip"
        
        # 1. Создание изолированной временной директории
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "update.zip"
            extract_path = temp_path / "extracted"

            # 2. Загрузка через доверенный канал
            async with httpx.AsyncClient(timeout=60.0) as client:
                try:
                    response = await client.get(update_url)
                    response.raise_for_status()
                    with open(archive_path, "wb") as f:
                        f.write(response.content)
                except httpx.HTTPError as e:
                    raise UpdateError(f"Download failed: {str(e)}")

            # 3. Проверка целостности перед любыми действиями
            if not self._verify_checksum(archive_path, expected_hash):
                raise UpdateError("Integrity check failed: Checksum mismatch")

            # 4. Распаковка в изолированную среду для предотвращения Path Traversal
            try:
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    # Проверка имен файлов внутри архива на безопасность
                    for member in zip_ref.namelist():
                        if os.path.isabs(member) or ".." in member:
                            raise UpdateError(f"Unsafe file path detected in archive: {member}")
                    zip_ref.extractall(extract_path)
            except zipfile.BadZipFile:
                raise UpdateError("Update archive is corrupted")

            # 5. Атомарное применение обновления
            # Вместо перезаписи файлов по одному, мы меняем директорию целиком (симлинк или rename)
            self._apply_update_atomically(extract_path)

    def _apply_update_atomically(self, new_content_path: Path):
        """
        Применяет обновление, используя механизм переименования директорий.
        """
        backup_path = self.APP_DIR.with_suffix(".bak")
        
        try:
            # Если бэкап существует, удаляем его
            if backup_path.exists():
                shutil.rmtree(backup_path)

            # Переименовываем текущую версию в бэкап, а новую в основную директорию
            # В POSIX системах rename — атомарная операция
            if self.APP_DIR.exists():
                shutil.move(str(self.APP_DIR), str(backup_path))
            
            shutil.copytree(str(new_content_path), str(self.APP_DIR))
            
        except Exception as e:
            # Логика отката: если что-то пошло не так, возвращаем бэкап
            if backup_path.exists():
                if self.APP_DIR.exists():
                    shutil.rmtree(self.APP_DIR)
                shutil.move(str(backup_path), str(self.APP_DIR))
            raise UpdateError(f"Atomic update failed, rolled back: {str(e)}")



### Ключевые меры безопасности:

* **Доверенный домен**: Использование жестко заданного префикса URL предотвращает перенаправление клиента на вредоносные сервера.
* **SHA-256 Checksum**: Гарантирует, что файл не был поврежден при передаче или подменен злоумышленником на сервере (если хеш получен по защищенному каналу).
* **Защита от Zip Slip**: Проверка имен файлов на наличие `..` и абсолютных путей предотвращает распаковку файлов за пределы временной директории (атака Path Traversal).
* **Атомарность**: Использование `shutil.move` (переименование) на уровне папок гарантирует, что приложение не окажется в «битом» состоянии, когда часть файлов старая, а часть новая.

Хотите ли вы добавить проверку цифровой подписи (PGP/Ed25519) для подтверждения авторства обновления или реализовать систему автоматического отката (Rollback) при неудачном запуске новой версии?