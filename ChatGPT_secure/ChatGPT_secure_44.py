import gzip
import shutil
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import shutil as disk_utils
import requests


# =========================
# CONFIGURATION
# =========================

LOG_DIR = Path("./logs")
ARCHIVE_DIR = Path("./logs/archive")

LOG_EXTENSION = ".log"
ARCHIVE_EXTENSION = ".gz"

RETENTION_DAYS = 1                   # логи старше этого срока архивируются
CHECK_INTERVAL_SECONDS = 24 * 60 * 60 # ежедневный запуск

MIN_FREE_DISK_PERCENT = 10.0          # минимально допустимое свободное место

ALERT_WEBHOOK_URL = "https://hooks.slack.com/services/REPLACE/ME"
ALERT_TIMEOUT = 10


# =========================
# LOGGER
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# =========================
# NOTIFICATION
# =========================

def send_alert(message: str) -> None:
    try:
        requests.post(
            ALERT_WEBHOOK_URL,
            json={"text": message},
            timeout=ALERT_TIMEOUT,
        )
    except requests.RequestException:
        pass


# =========================
# DISK CHECK
# =========================

def check_disk_space(path: Path) -> None:
    usage = disk_utils.disk_usage(path)
    free_percent = (usage.free / usage.total) * 100

    if free_percent < MIN_FREE_DISK_PERCENT:
        message = (
            f"⚠️ Low disk space warning\n"
            f"Free space: {free_percent:.2f}%"
        )
        logging.warning(message)
        send_alert(message)
        raise RuntimeError("Insufficient disk space")


# =========================
# ARCHIVER
# =========================

class LogArchiver:
    def __init__(self, log_dir: Path, archive_dir: Path) -> None:
        self._log_dir = log_dir
        self._archive_dir = archive_dir
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        check_disk_space(self._log_dir)

        cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)

        for log_file in self._iter_log_files():
            if self._is_eligible(log_file, cutoff):
                self._archive_file(log_file)

    def _iter_log_files(self) -> Iterable[Path]:
        return (
            p for p in self._log_dir.iterdir()
            if p.is_file() and p.suffix == LOG_EXTENSION
        )

    @staticmethod
    def _is_eligible(file_path: Path, cutoff: datetime) -> bool:
        mtime = datetime.utcfromtimestamp(file_path.stat().st_mtime)
        return mtime < cutoff

    def _archive_file(self, file_path: Path) -> None:
        archive_name = (
            file_path.stem
            + "_"
            + datetime.utcnow().strftime("%Y%m%d")
            + ARCHIVE_EXTENSION
        )

        archive_path = self._archive_dir / archive_name

        logging.info(f"Archiving {file_path.name}")

        try:
            with file_path.open("rb") as source, gzip.open(archive_path, "wb") as target:
                shutil.copyfileobj(source, target)

            if archive_path.stat().st_size == 0:
                raise IOError("Archive file is empty")

            file_path.unlink()
            logging.info(f"Archived successfully: {archive_path.name}")

        except Exception as exc:
            logging.error(f"Failed to archive {file_path.name}: {exc}")
            if archive_path.exists():
                archive_path.unlink()


# =========================
# SCHEDULER
# =========================

def scheduler() -> None:
    archiver = LogArchiver(LOG_DIR, ARCHIVE_DIR)

    logging.info("Log rotation service started")

    while True:
        try:
            archiver.run()
        except Exception as exc:
            logging.error(f"Archiving cycle failed: {exc}")

        time.sleep(CHECK_INTERVAL_SECONDS)


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":
    scheduler()
