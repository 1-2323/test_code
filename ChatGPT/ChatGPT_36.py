import hashlib
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import requests


# ==================================================
# Исключения
# ==================================================

class UpdateError(Exception):
    """Базовая ошибка обновления ПО."""


class ChecksumMismatchError(UpdateError):
    """Контрольная сумма не совпала."""


class DownloadError(UpdateError):
    """Ошибка загрузки архива."""


class ExtractionError(UpdateError):
    """Ошибка распаковки архива."""


# ==================================================
# Конфигурация логирования
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ==================================================
# UpdateClient
# ==================================================

class UpdateClient:
    """
    Клиент автоматического обновления ПО.
    """

    def __init__(
        self,
        download_url: str,
        expected_checksum: str,
        workdir: Path,
        timeout: int = 30,
    ) -> None:
        self._url = download_url
        self._checksum = expected_checksum.lower()
        self._workdir = workdir
        self._timeout = timeout

    # =========================
    # Public API
    # =========================

    def update(self) -> None:
        """
        Основной процесс обновления.
        """
        logger.info("Starting update process")

        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = Path(tmp_dir) / "update.zip"

            self._download_archive(archive_path)
            self._verify_checksum(archive_path)
            self._extract_archive(archive_path)

        logger.info("Update completed successfully")

    # =========================
    # Внутренняя логика
    # =========================

    def _download_archive(self, destination: Path) -> None:
        """
        Скачивает архив обновления.
        """
        logger.info("Downloading update from %s", self._url)

        try:
            with requests.get(
                self._url,
                stream=True,
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                with open(destination, "wb") as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
        except requests.RequestException as exc:
            raise DownloadError("Failed to download update") from exc

    def _verify_checksum(self, file_path: Path) -> None:
        """
        Проверяет SHA-256 контрольную сумму архива.
        """
        logger.info("Verifying checksum")

        sha256 = hashlib.sha256()

        try:
            with open(file_path, "rb") as file:
                for block in iter(lambda: file.read(4096), b""):
                    sha256.update(block)
        except OSError as exc:
            raise ChecksumMismatchError("Failed to read archive") from exc

        actual_checksum = sha256.hexdigest()

        if actual_checksum != self._checksum:
            raise ChecksumMismatchError(
                f"Checksum mismatch: {actual_checksum}"
            )

    def _extract_archive(self, archive_path: Path) -> None:
        """
        Безопасно распаковывает архив в рабочую директорию.
        """
        logger.info("Extracting update to %s", self._workdir)

        try:
            with zipfile.ZipFile(archive_path) as archive:
                self._safe_extract(archive, self._workdir)
        except zipfile.BadZipFile as exc:
            raise ExtractionError("Invalid ZIP archive") from exc

    @staticmethod
    def _safe_extract(
        archive: zipfile.ZipFile,
        destination: Path,
    ) -> None:
        """
        Защита от Zip Slip (path traversal).
        """
        destination = destination.resolve()

        for member in archive.namelist():
            target_path = (destination / member).resolve()

            if not str(target_path).startswith(str(destination)):
                raise ExtractionError("Unsafe path detected in archive")

        archive.extractall(destination)
