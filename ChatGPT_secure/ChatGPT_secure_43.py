import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Tuple
from pathlib import Path


# =========================
# CONFIGURATION
# =========================

LOG_FILE_PATH = Path("access.log")
TARGET_ENDPOINT = "/login"
REQUEST_THRESHOLD = 100          # запросов
WINDOW_SECONDS = 60              # временное окно (1 минута)
POLL_INTERVAL = 0.5              # интервал чтения файла


# =========================
# DATA MODELS
# =========================

@dataclass(frozen=True)
class LogEvent:
    timestamp: float
    ip: str
    path: str


# =========================
# LOG PARSER
# =========================

def parse_log_line(line: str) -> LogEvent | None:
    """
    Ожидаемый формат строки (пример):
    1690000000.123 192.168.1.10 /login
    """
    try:
        parts = line.strip().split()
        if len(parts) != 3:
            return None

        timestamp = float(parts[0])
        ip = parts[1]
        path = parts[2]

        return LogEvent(timestamp=timestamp, ip=ip, path=path)
    except (ValueError, IndexError):
        return None


# =========================
# ANOMALY DETECTOR
# =========================

class LoginAnomalyDetector:
    def __init__(self) -> None:
        self._events: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def process_event(self, event: LogEvent) -> None:
        if event.path != TARGET_ENDPOINT:
            return

        key = (event.ip, event.path)

        with self._lock:
            timestamps = self._events[key]
            timestamps.append(event.timestamp)

            self._evict_old(timestamps, event.timestamp)

            if len(timestamps) > REQUEST_THRESHOLD:
                self._report_anomaly(event.ip, len(timestamps))

    @staticmethod
    def _evict_old(timestamps: Deque[float], now: float) -> None:
        while timestamps and now - timestamps[0] > WINDOW_SECONDS:
            timestamps.popleft()

    @staticmethod
    def _report_anomaly(ip: str, count: int) -> None:
        print(
            f"[ANOMALY] Suspicious activity detected: "
            f"{count} requests to /login from IP {ip} within 1 minute"
        )


# =========================
# LOG TAILER
# =========================

class LogTailer(threading.Thread):
    def __init__(self, file_path: Path, detector: LoginAnomalyDetector) -> None:
        super().__init__(daemon=True)
        self._file_path = file_path
        self._detector = detector
        self._stop_event = threading.Event()

    def run(self) -> None:
        with self._file_path.open("r", encoding="utf-8") as file:
            file.seek(0, 2)  # переход в конец файла

            while not self._stop_event.is_set():
                line = file.readline()
                if not line:
                    time.sleep(POLL_INTERVAL)
                    continue

                event = parse_log_line(line)
                if event:
                    self._detector.process_event(event)

    def stop(self) -> None:
        self._stop_event.set()


# =========================
# ENTRY POINT
# =========================

def main() -> None:
    detector = LoginAnomalyDetector()
    tailer = LogTailer(LOG_FILE_PATH, detector)

    print("[INFO] Starting access log analyzer...")
    tailer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Stopping analyzer...")
        tailer.stop()


if __name__ == "__main__":
    main()
