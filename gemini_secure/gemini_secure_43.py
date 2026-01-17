import asyncio
import re
import time
from collections import defaultdict, deque
from typing import Dict, Final, Pattern

# --- Конфигурация анализатора ---
LOG_FILE_PATH: Final[str] = "access.log"
TARGET_ENDPOINT: Final[str] = "/login"
MAX_REQUESTS_PER_MINUTE: Final[int] = 100
WINDOW_SIZE: Final[int] = 60  # Секунд

# Регулярное выражение для парсинга стандартного формата логов (Common Log Format)
# Извлекает: IP и Path
LOG_PATTERN: Final[Pattern] = re.compile(
    r'(?P<ip>\d{1,3}(?:\.\d{1,3}){3}).*"(?:GET|POST) (?P<path>\S+) '
)

class AccessLogAnalyzer:
    """Анализатор логов для выявления аномальной активности в реальном времени."""

    def __init__(self):
        # Хранилище временных меток запросов: {ip: deque([timestamps])}
        self.activity_window: Dict[str, deque] = defaultdict(deque)

    def _cleanup_old_data(self, ip: str, current_time: float):
        """Удаляет из окна запросы, которые старше WINDOW_SIZE."""
        window = self.activity_window[ip]
        while window and window[0] <= current_time - WINDOW_SIZE:
            window.popleft()

    async def _process_line(self, line: str):
        """Парсит строку и проверяет порог активности."""
        match = LOG_PATTERN.search(line)
        if not match:
            return

        ip = match.group('ip')
        path = match.group('path')

        if path == TARGET_ENDPOINT:
            current_time = time.time()
            self._cleanup_old_data(ip, current_time)
            
            # Регистрируем новый запрос
            self.activity_window[ip].append(current_time)
            
            # Проверка порога
            request_count = len(self.activity_window[ip])
            if request_count > MAX_REQUESTS_PER_MINUTE:
                self._report_anomaly(ip, request_count)

    def _report_anomaly(self, ip: str, count: int):
        """Фиксация аномалии без блокировки процесса."""
        print(f"!!! ANOMALY DETECTED !!! | IP: {ip} | Requests: {count} in last {WINDOW_SIZE}s | Path: {TARGET_ENDPOINT}")

    async def watch_log(self):
        """Асинхронное чтение файла лога (имитация tail -f)."""
        print(f"Monitoring {LOG_FILE_PATH} for {TARGET_ENDPOINT} brute-force...")
        
        try:
            with open(LOG_FILE_PATH, "r") as f:
                # Переходим в конец файла
                f.seek(0, 2)
                
                while True:
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.1)  # Ожидание новых строк
                        continue
                    
                    await self._process_line(line)
        except FileNotFoundError:
            print(f"Error: Log file {LOG_FILE_PATH} not found.")

# --- Запуск ---

if __name__ == "__main__":
    analyzer = AccessLogAnalyzer()
    try:
        asyncio.run(analyzer.watch_log())
    except KeyboardInterrupt:
        print("\nStopping analyzer...")