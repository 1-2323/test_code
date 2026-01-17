import gzip
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import requests


LOG_DIR = Path("/var/log/myapp")
ARCHIVE_DIR = LOG_DIR / "archive"
RETENTION_DAYS = 7
DISK_THRESHOLD_PERCENT = 90
CHECK_INTERVAL_SECONDS = 86400

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id

    def send(self, message: str) -> None:
        try:
            requests.post(
                self._url,
                json={"chat_id": self._chat_id, "text": message},
                timeout=5,
            )
        except Exception:
            pass


class LogRotator:
    def __init__(self, log_dir: Path, archive_dir: Path) -> None:
        self._log_dir = log_dir
        self._archive_dir = archive_dir
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    def rotate(self) -> None:
        cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
        for log_file in self._iter_logs():
            mtime = datetime.utcfromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff:
                self._archive(log_file)

    def _iter_logs(self) -> Iterable[Path]:
        return (
            f for f in self._log_dir.iterdir()
            if f.is_file() and not f.name.endswith(".gz")
        )

    def _archive(self, file_path: Path) -> None:
        archived = self._archive_dir / f"{file_path.name}.gz"
        with open(file_path, "rb") as src, gzip.open(archived, "wb") as dst:
            shutil.copyfileobj(src, dst)
        file_path.unlink()


class DiskMonitor:
    def __init__(self, path: Path, threshold_percent: int) -> None:
        self._path = path
        self._threshold = threshold_percent

    def is_full(self) -> bool:
        usage = shutil.disk_usage(self._path)
        used_percent = int((usage.used / usage.total) * 100)
        return used_percent >= self._threshold

    def usage_percent(self) -> int:
        usage = shutil.disk_usage(self._path)
        return int((usage.used / usage.total) * 100)


def main() -> None:
    notifier = TelegramNotifier(
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
    )
    rotator = LogRotator(LOG_DIR, ARCHIVE_DIR)
    disk_monitor = DiskMonitor(LOG_DIR, DISK_THRESHOLD_PERCENT)

    while True:
        rotator.rotate()

        if disk_monitor.is_full():
            notifier.send(
                f"⚠️ Disk usage critical: {disk_monitor.usage_percent()}%"
            )

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
