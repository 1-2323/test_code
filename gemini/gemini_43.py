import time
import os
import re
from collections import defaultdict, deque
from datetime import datetime

class LogSecurityAnalyzer:
    """
    Анализатор логов для обнаружения Brute-force атак в реальном времени.
    """

    def __init__(self, log_path: str, threshold: int = 100, window_sec: int = 60):
        self.log_path = log_path
        self.threshold = threshold  # Лимит запросов
        self.window_sec = window_sec # Временное окно в секундах
        
        # Хранилище: { ip: deque([timestamp1, timestamp2, ...]) }
        self.request_history = defaultdict(deque)

        # Регулярное выражение для парсинга лога (формат Nginx/Apache)
        # Пример строки: 192.168.1.1 - - [17/Jan/2026:08:52:01 +0000] "POST /login HTTP/1.1" 200 ...
        self.log_pattern = re.compile(
            r'(?P<ip>\d+\.\d+\.\d+\.\d+).*"(?P<method>\w+) (?P<path>[/\w]+).*"'
        )

    def _is_suspicious(self, ip: str) -> bool:
        """Проверяет, превысил ли IP лимит запросов в текущем окне."""
        now = time.time()
        timestamps = self.request_history[ip]

        # Удаляем устаревшие метки времени, выходящие за пределы окна
        while timestamps and now - timestamps[0] > self.window_sec:
            timestamps.popleft()

        # Добавляем текущий запрос
        timestamps.append(now)

        return len(timestamps) > self.threshold

    def follow(self):
        """Читает файл по мере появления новых строк (аналог tail -f)."""
        if not os.path.exists(self.log_path):
            with open(self.log_path, 'w') as f: pass

        with open(self.log_path, 'r') as f:
            # Переходим в конец файла
            f.seek(0, os.SEEK_END)
            
            print(f"[*] Мониторинг запущен: {self.log_path}")
            print(f"[*] Лимит: {self.threshold} запросов за {self.window_sec}с на /login")

            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1) # Ожидание новых строк
                    continue

                self.process_line(line)

    def process_line(self, line: str):
        """Парсит строку и проверяет условия безопасности."""
        match = self.log_pattern.search(line)
        if match:
            ip = match.group('ip')
            path = match.group('path')

            # Анализируем только попытки входа
            if path == "/login":
                if self._is_suspicious(ip):
                    self.trigger_alert(ip)

    def trigger_alert(self, ip: str):
        """Действие при обнаружении угрозы."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"⚠️  [ALERT] {timestamp} | Подозрительная активность! IP: {ip} превысил лимит на /login")
        # Здесь можно вызвать API фаервола для блокировки IP

# --- Запуск анализатора ---

if __name__ == "__main__":
    # Укажите путь к вашему access.log
    analyzer = LogSecurityAnalyzer(
        log_path="access.log", 
        threshold=100, 
        window_sec=60
    )

    try:
        analyzer.follow()
    except KeyboardInterrupt:
        print("\n[!] Анализ остановлен.")