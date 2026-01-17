import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Deque, Dict, Iterator, Optional


# ==================================================
# Конфигурация
# ==================================================

LOG_FILE_PATH = "/var/log/nginx/access.log"
TARGET_ENDPOINT = "/login"
MAX_REQUESTS_PER_MINUTE = 100
TIME_WINDOW_SECONDS = 60
ALERT_COOLDOWN_SECONDS = 300


# ==================================================
# Модели
# ==================================================

@dataclass(frozen=True)
class LogEntry:
    ip: str
    endpoint: str
    timestamp: datetime


# ==================================================
# Парсер логов
# ==================================================

class LogParser:
    """
    Парсит строки access-лога (nginx-формат).
    """

    _log_pattern = re.compile(
        r'(?P<ip>\d+\.\d+\.\d+\.\d+).+?\[(?P<time>.+?)\].+?"\w+ (?P<endpoint>/\S*)'
    )

    @staticmethod
    def parse(line: str) -> Optional[LogEntry]:
        match = LogParser._log_pattern.search(line)
        if not match:
            return None

        try:
            timestamp = datetime.strptime(
                match.group("time"),
                "%d/%b/%Y:%H:%M:%S %z",
            ).replace(tzinfo=None)
        except ValueError:
            return None

        return LogEntry(
            ip=match.group("ip"),
            endpoint=match.group("endpoint"),
            timestamp=timestamp,
        )


# ==================================================
# Детектор подозрительной активности
# ==================================================

class SuspiciousActivityDetector:
    """
    Отслеживает частоту запросов к /login по IP.
    """

    def __init__(self) -> None:
        self._requests: Dict[str, Deque[datetime]] = defaultdict(deque)
        self._last_alert: Dict[str, datetime] = {}

    def process(self, entry: LogEntry) -> None:
        if entry.endpoint != TARGET_ENDPOINT:
            return

        timestamps = self._requests[entry.ip]
        timestamps.append(entry.timestamp)

        self._cleanup_old(timestamps, entry.timestamp)

        if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
            self._alert(entry.ip, len(timestamps), entry.timestamp)

    def _cleanup_old(
        self,
        timestamps: Deque[datetime],
        now: datetime,
    ) -> None:
        while timestamps and (now - timestamps[0]).seconds > TIME_WINDOW_SECONDS:
            timestamps.popleft()

    def _alert(self, ip: str, count: int, now: datetime) -> None:
        last = self._last_alert.get(ip)

        if last and (now - last).seconds < ALERT_COOLDOWN_SECONDS:
            return

        self._last_alert[ip] = now

        print(
            "🚨 SUSPICIOUS ACTIVITY DETECTED\n"
            f"IP: {ip}\n"
            f"Requests to {TARGET_ENDPOINT}: {count} per minute\n"
            f"Time: {now.isoformat()}\n"
        )


# ==================================================
# Tail логов (реальное время)
# ==================================================

class LogTailer:
    """
    Читает лог-файл в режиме реального времени.
    """

    def __init__(self, file_path: str) -> None:
        self._file_path = file_path

    def follow(self) -> Iterator[str]:
        with open(self._file_path, "r") as file:
            file.seek(0, 2)  # jump to EOF

            while True:
                line = file.readline()
                if not line:
                    time.sleep(0.1)
                    continue

                yield line


# ==================================================
# Запуск
# ==================================================

def main() -> None:
    print("[INFO] Access log analyzer started")

    tailer = LogTailer(LOG_FILE_PATH)
    detector = SuspiciousActivityDetector()

    for line in tailer.follow():
        entry = LogParser.parse(line)
        if entry:
            detector.process(entry)


if __name__ == "__main__":
    main()
