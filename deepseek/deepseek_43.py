import re
import time
from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import threading
import json


class AccessLogAnalyzer:
    """
    Анализатор логов доступа для выявления подозрительной активности.
    """
    
    # Регулярное выражение для парсинга логов Common Log Format
    LOG_PATTERN = re.compile(
        r'(?P<ip>\d+\.\d+\.\d+\.\d+)\s+'
        r'-\s+-\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\w+)\s+'
        r'(?P<path>[^"]+)\s+'
        r'HTTP/\d\.\d"\s+'
        r'(?P<status>\d{3})\s+'
        r'(?P<size>\d+)'
    )
    
    def __init__(
        self,
        log_file: str,
        alert_threshold: int = 100,  # запросов в минуту
        check_interval: int = 10,    # секунды
        endpoint_pattern: str = r'/login'
    ):
        """
        Инициализация анализатора логов.
        
        Args:
            log_file: Путь к файлу логов
            alert_threshold: Порог для оповещения (запросов в минуту)
            check_interval: Интервал проверки в секундах
            endpoint_pattern: Паттерн для отслеживаемого эндпоинта
        """
        self.log_file = log_file
        self.alert_threshold = alert_threshold
        self.check_interval = check_interval
        self.endpoint_pattern = re.compile(endpoint_pattern)
        
        # Структуры для хранения данных
        self.request_logs: Dict[str, deque] = defaultdict(deque)
        self.alerts: List[Dict[str, str]] = []
        
        self.is_running = False
        self.last_position = 0
        
        print(f"Анализатор логов инициализирован для файла: {log_file}")
        print(f"Порог оповещения: {alert_threshold} запросов в минуту")
    
    def _parse_log_line(self, line: str) -> Optional[Dict[str, str]]:
        """
        Парсит строку лога.
        
        Args:
            line: Строка лога
            
        Returns:
            Словарь с распарсенными данными или None при ошибке
        """
        match = self.LOG_PATTERN.match(line.strip())
        if match:
            return match.groupdict()
        return None
    
    def _is_target_endpoint(self, path: str) -> bool:
        """
        Проверяет, является ли путь целевым эндпоинтом.
        
        Args:
            path: Путь из лога
            
        Returns:
            True если путь соответствует паттерну, иначе False
        """
        return bool(self.endpoint_pattern.search(path))
    
    def _read_new_lines(self) -> List[str]:
        """
        Читает новые строки из файла лога.
        
        Returns:
            Список новых строк
        """
        try:
            with open(self.log_file, 'r', encoding='utf-8') as file:
                # Перемещаемся к последней прочитанной позиции
                file.seek(self.last_position)
                
                # Читаем новые строки
                new_lines = file.readlines()
                
                # Обновляем позицию
                self.last_position = file.tell()
                
                return new_lines
                
        except FileNotFoundError:
            print(f"Файл лога не найден: {self.log_file}")
            return []
        except Exception as e:
            print(f"Ошибка чтения файла лога: {str(e)}")
            return []
    
    def _clean_old_requests(self) -> None:
        """
        Удаляет старые записи из логов (старше 1 минуты).
        """
        cutoff_time = datetime.now() - timedelta(minutes=1)
        
        for ip in list(self.request_logs.keys()):
            # Удаляем записи старше 1 минуты
            while (self.request_logs[ip] and 
                   self.request_logs[ip][0] < cutoff_time):
                self.request_logs[ip].popleft()
            
            # Если после очистки записей не осталось, удаляем IP
            if not self.request_logs[ip]:
                del self.request_logs[ip]
    
    def _check_for_suspicious_activity(self) -> None:
        """
        Проверяет наличие подозрительной активности.
        """
        current_time = datetime.now()
        
        for ip, timestamps in self.request_logs.items():
            # Подсчитываем запросы за последнюю минуту
            requests_count = len([
                ts for ts in timestamps 
                if ts > current_time - timedelta(minutes=1)
            ])
            
            # Проверяем превышение порога
            if requests_count > self.alert_threshold:
                self._generate_alert(ip, requests_count)
    
    def _generate_alert(self, ip: str, request_count: int) -> None:
        """
        Генерирует оповещение о подозрительной активности.
        
        Args:
            ip: IP адрес
            request_count: Количество запросов
        """
        alert_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        alert = {
            "timestamp": alert_time,
            "ip_address": ip,
            "request_count": request_count,
            "threshold": self.alert_threshold,
            "endpoint": self.endpoint_pattern.pattern,
            "message": (
                f"ПОДОЗРИТЕЛЬНАЯ АКТИВНОСТЬ!\n"
                f"Время: {alert_time}\n"
                f"IP: {ip}\n"
                f"Запросов к /login: {request_count} (порог: {self.alert_threshold})\n"
                f"Рекомендуется проверить блокировку IP"
            )
        }
        
        self.alerts.append(alert)
        
        # Выводим оповещение в консоль
        print("\n" + "="*60)
        print(alert["message"])
        print("="*60 + "\n")
        
        # Сохраняем оповещение в файл
        self._save_alert_to_file(alert)
    
    def _save_alert_to_file(self, alert: Dict[str, str]) -> None:
        """
        Сохраняет оповещение в файл.
        
        Args:
            alert: Словарь с данными оповещения
        """
        try:
            with open("security_alerts.log", "a", encoding="utf-8") as file:
                file.write(json.dumps(alert, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Ошибка сохранения оповещения: {str(e)}")
    
    def _monitor_logs(self) -> None:
        """
        Основной цикл мониторинга логов.
        """
        print("Запущен мониторинг логов в реальном времени...")
        
        while self.is_running:
            try:
                # Читаем новые строки
                new_lines = self._read_new_lines()
                
                # Парсим новые строки
                for line in new_lines:
                    log_data = self._parse_log_line(line)
                    
                    if log_data and self._is_target_endpoint(log_data["path"]):
                        # Добавляем запись в лог
                        ip = log_data["ip"]
                        timestamp_str = log_data["timestamp"]
                        
                        try:
                            # Парсим timestamp из лога
                            timestamp = datetime.strptime(
                                timestamp_str, "%d/%b/%Y:%H:%M:%S %z"
                            )
                            # Конвертируем в локальное время без временной зоны
                            timestamp = timestamp.replace(tzinfo=None)
                        except (ValueError, AttributeError):
                            # Если не удалось распарсить, используем текущее время
                            timestamp = datetime.now()
                        
                        self.request_logs[ip].append(timestamp)
                
                # Очищаем старые записи
                self._clean_old_requests()
                
                # Проверяем подозрительную активность
                self._check_for_suspicious_activity()
                
                # Ждем перед следующей проверкой
                time.sleep(self.check_interval)
                
            except Exception as e:
                print(f"Ошибка в мониторе логов: {str(e)}")
                time.sleep(self.check_interval)
    
    def start(self) -> None:
        """Запускает мониторинг логов"""
        self.is_running = True
        
        # Запускаем мониторинг в отдельном потоке
        monitor_thread = threading.Thread(target=self._monitor_logs, daemon=True)
        monitor_thread.start()
        
        print("Мониторинг логов запущен. Нажмите Ctrl+C для остановки.")
        
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self) -> None:
        """Останавливает мониторинг"""
        self.is_running = False
        print("Мониторинг логов остановлен.")
        
        # Выводим статистику
        self._print_statistics()
    
    def _print_statistics(self) -> None:
        """Выводит статистику анализа"""
        print("\n" + "="*60)
        print("СТАТИСТИКА АНАЛИЗА ЛОГОВ")
        print("="*60)
        
        total_ips = len(self.request_logs)
        total_requests = sum(len(logs) for logs in self.request_logs.values())
        total_alerts = len(self.alerts)
        
        print(f"Уникальных IP: {total_ips}")
        print(f"Всего запросов: {total_requests}")
        print(f"Оповещений: {total_alerts}")
        
        if self.request_logs:
            print("\nТоп 5 IP по количеству запросов:")
            sorted_ips = sorted(
                self.request_logs.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )[:5]
            
            for ip, logs in sorted_ips:
                print(f"  {ip}: {len(logs)} запросов")


# Пример использования
if __name__ == "__main__":
    # Создаем анализатор логов
    analyzer = AccessLogAnalyzer(
        log_file="access.log",  # Путь к файлу логов
        alert_threshold=100,    # Порог для оповещения
        check_interval=5,       # Интервал проверки в секундах
        endpoint_pattern=r'/login'  # Отслеживаемый эндпоинт
    )
    
    # Запускаем анализ
    analyzer.start()