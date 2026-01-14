import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Tuple, Optional
import json

class FailedLoginAnalyzer:
    """
    Анализатор логов для детекции аномального количества неудачных входов
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Инициализация анализатора
        
        Args:
            config: Конфигурационный словарь с параметрами
        """
        self.config = config or self._get_default_config()
        
        # Словарь для хранения статистики по IP-адресам
        # Структура: {ip: {window_start: datetime, attempts: List[datetime]}}
        self.ip_stats: Dict[str, Dict] = defaultdict(lambda: {
            'window_start': None,
            'attempts': []
        })
        
        # Настройка логирования
        self._setup_logging()
        
        # Паттерны для парсинга логов (можно расширять)
        self.patterns = {
            'failed_login': re.compile(
                self.config['log_patterns']['failed_login'],
                re.IGNORECASE
            ),
            'ip_address': re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
        }
        
        self.logger = logging.getLogger(__name__)
        
    def _get_default_config(self) -> Dict:
        """Возвращает конфигурацию по умолчанию"""
        return {
            # Пороговые значения
            'thresholds': {
                'max_attempts_per_window': 5,      # Максимальное количество попыток в окне
                'time_window_minutes': 10,         # Временное окно в минутах
                'alert_cooldown_minutes': 30       # Задержка между алертами для одного IP
            },
            
            # Паттерны для логов
            'log_patterns': {
                'failed_login': r'(?:failed|invalid|incorrect|authentication failure).*?(?P<ip>\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b)',
            },
            
            # Настройки вывода
            'alert_levels': {
                'WARNING': 5,
                'CRITICAL': 10
            }
        }
    
    def _setup_logging(self):
        """Настройка системы логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('security_alerts.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
    
    def parse_log_line(self, line: str) -> Optional[Tuple[str, datetime]]:
        """
        Парсит строку лога и извлекает информацию о неудачном входе
        
        Args:
            line: Строка лога
            
        Returns:
            Кортеж (IP-адрес, timestamp) или None
        """
        try:
            # Попытка извлечь timestamp из строки (примерный формат)
            time_match = re.search(r'\[?(?P<timestamp>\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]?', line)
            if time_match:
                timestamp = datetime.strptime(time_match.group('timestamp'), '%Y-%m-%d %H:%M:%S')
            else:
                timestamp = datetime.now()
            
            # Поиск информации о неудачном входе
            failed_match = self.patterns['failed_login'].search(line)
            if failed_match:
                ip_address = failed_match.group('ip')
                return ip_address, timestamp
            
            # Альтернативный поиск по ключевым словам
            failed_keywords = ['failed', 'invalid', 'incorrect', 'authentication failure']
            if any(keyword in line.lower() for keyword in failed_keywords):
                ip_match = self.patterns['ip_address'].search(line)
                if ip_match:
                    return ip_match.group(), timestamp
                    
        except Exception as e:
            self.logger.error(f"Ошибка парсинга строки лога: {e}")
        
        return None
    
    def update_ip_stats(self, ip: str, timestamp: datetime):
        """
        Обновляет статистику для IP-адреса
        
        Args:
            ip: IP-адрес
            timestamp: Время попытки входа
        """
        stats = self.ip_stats[ip]
        
        # Инициализация окна времени
        if stats['window_start'] is None:
            stats['window_start'] = timestamp
            stats['attempts'] = []
        
        # Очистка старых попыток за пределами временного окна
        window_duration = timedelta(minutes=self.config['thresholds']['time_window_minutes'])
        cutoff_time = timestamp - window_duration
        
        # Удаляем попытки старше временного окна
        stats['attempts'] = [attempt_time for attempt_time in stats['attempts'] 
                           if attempt_time > cutoff_time]
        
        # Если все попытки устарели, сбрасываем окно
        if not stats['attempts']:
            stats['window_start'] = timestamp
        
        # Добавляем текущую попытку
        stats['attempts'].append(timestamp)
    
    def check_thresholds(self, ip: str, timestamp: datetime) -> Optional[str]:
        """
        Проверяет превышение пороговых значений для IP-адреса
        
        Args:
            ip: IP-адрес
            timestamp: Время последней попытки
            
        Returns:
            Уровень угрозы или None
        """
        stats = self.ip_stats[ip]
        attempts_count = len(stats['attempts'])
        
        # Получаем пороговые значения
        warning_threshold = self.config['thresholds']['max_attempts_per_window']
        critical_threshold = self.config['alert_levels']['CRITICAL']
        
        # Определяем уровень угрозы
        if attempts_count >= critical_threshold:
            return 'CRITICAL'
        elif attempts_count >= warning_threshold:
            return 'WARNING'
        
        return None
    
    def generate_alert(self, ip: str, threat_level: str, timestamp: datetime, details: Dict):
        """
        Генерирует и сохраняет alert
        
        Args:
            ip: IP-адрес
            threat_level: Уровень угрозы
            timestamp: Время события
            details: Дополнительные детали
        """
        alert = {
            'timestamp': timestamp.isoformat(),
            'ip_address': ip,
            'threat_level': threat_level,
            'attempts_count': len(self.ip_stats[ip]['attempts']),
            'time_window_minutes': self.config['thresholds']['time_window_minutes'],
            'details': details,
            'message': f"Обнаружена подозрительная активность с IP {ip}: "
                      f"{len(self.ip_stats[ip]['attempts'])} неудачных попыток входа "
                      f"за последние {self.config['thresholds']['time_window_minutes']} минут"
        }
        
        # Логирование alert
        log_message = f"ALERT [{threat_level}] {alert['message']}"
        
        if threat_level == 'CRITICAL':
            self.logger.critical(log_message)
        elif threat_level == 'WARNING':
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)
        
        # Сохранение alert в файл
        try:
            with open('alerts.json', 'a') as f:
                json.dump(alert, f)
                f.write('\n')
        except Exception as e:
            self.logger.error(f"Ошибка сохранения alert: {e}")
        
        # Вывод в консоль
        print(f"\n{'='*60}")
        print(f"🚨 СИСТЕМА ОБНАРУЖЕНИЯ АТАК")
        print(f"{'='*60}")
        print(f"Время: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Уровень угрозы: {threat_level}")
        print(f"IP-адрес: {ip}")
        print(f"Неудачных попыток: {len(self.ip_stats[ip]['attempts'])}")
        print(f"Временное окно: {self.config['thresholds']['time_window_minutes']} мин")
        print(f"{'='*60}\n")
    
    def analyze_log_file(self, log_file_path: str, realtime: bool = False):
        """
        Анализирует файл логов
        
        Args:
            log_file_path: Путь к файлу логов
            realtime: Режим реального времени (слежение за файлом)
        """
        self.logger.info(f"Начало анализа логов из файла: {log_file_path}")
        
        try:
            if realtime:
                # Режим реального времени
                with open(log_file_path, 'r') as log_file:
                    # Перемещаемся в конец файла
                    log_file.seek(0, 2)
                    
                    while True:
                        line = log_file.readline()
                        if line:
                            self.process_log_line(line)
                        else:
                            time.sleep(0.1)  # Небольшая пауза для новых данных
            else:
                # Однократный анализ всего файла
                with open(log_file_path, 'r') as log_file:
                    for line in log_file:
                        self.process_log_line(line)
                        
        except FileNotFoundError:
            self.logger.error(f"Файл логов не найден: {log_file_path}")
        except KeyboardInterrupt:
            self.logger.info("Анализ остановлен пользователем")
        except Exception as e:
            self.logger.error(f"Ошибка при анализе логов: {e}")
    
    def process_log_line(self, line: str):
        """
        Обрабатывает одну строку лога
        
        Args:
            line: Строка лога
        """
        result = self.parse_log_line(line)
        
        if result:
            ip, timestamp = result
            self.update_ip_stats(ip, timestamp)
            
            threat_level = self.check_thresholds(ip, timestamp)
            if threat_level:
                details = {
                    'log_line': line.strip(),
                    'attempt_times': [t.strftime('%H:%M:%S') for t in self.ip_stats[ip]['attempts']]
                }
                self.generate_alert(ip, threat_level, timestamp, details)
    
    def analyze_log_stream(self, log_stream):
        """
        Анализирует поток логов (например, из sys.stdin)
        
        Args:
            log_stream: Поток данных с логами
        """
        self.logger.info("Начало анализа потока логов...")
        
        try:
            for line in log_stream:
                if line.strip():
                    self.process_log_line(line)
        except KeyboardInterrupt:
            self.logger.info("Анализ остановлен пользователем")
        except Exception as e:
            self.logger.error(f"Ошибка при анализе потока логов: {e}")
    
    def cleanup_old_data(self, older_than_hours: int = 24):
        """
        Очищает старые данные из памяти
        
        Args:
            older_than_hours: Удалить данные старше указанного количества часов
        """
        cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
        ips_to_remove = []
        
        for ip, stats in self.ip_stats.items():
            # Проверяем, есть ли активность за указанный период
            if stats['attempts']:
                latest_attempt = max(stats['attempts'])
                if latest_attempt < cutoff_time:
                    ips_to_remove.append(ip)
        
        for ip in ips_to_remove:
            del self.ip_stats[ip]
        
        if ips_to_remove:
            self.logger.info(f"Очищены данные для {len(ips_to_remove)} IP-адресов")


def main():
    """Основная функция для запуска анализатора"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Анализатор неудачных попыток входа')
    parser.add_argument('--log-file', type=str, help='Путь к файлу логов')
    parser.add_argument('--realtime', action='store_true', help='Режим реального времени')
    parser.add_argument('--stdin', action='store_true', help='Чтение логов из stdin')
    parser.add_argument('--config', type=str, help='Путь к файлу конфигурации JSON')
    
    args = parser.parse_args()
    
    # Загрузка конфигурации
    config = None
    if args.config:
        try:
            with open(args.config, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки конфигурации: {e}")
            return
    
    # Создание анализатора
    analyzer = FailedLoginAnalyzer(config)
    
    # Выбор режима работы
    if args.stdin:
        # Анализ из stdin
        analyzer.analyze_log_stream(sys.stdin)
    elif args.log_file:
        # Анализ файла
        analyzer.analyze_log_file(args.log_file, args.realtime)
    else:
        parser.print_help()
        print("\nПримеры использования:")
        print("  python analyzer.py --log-file /var/log/auth.log --realtime")
        print("  cat access.log | python analyzer.py --stdin")
        print("  python analyzer.py --log-file failed_logins.txt")


if __name__ == "__main__":
    main()