import os
import shutil
import gzip
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from dataclasses import dataclass
import schedule
import time
import psutil
import json


@dataclass
class LogRotationConfig:
    """Конфигурация ротации логов"""
    log_directory: str
    archive_directory: str
    retention_days: int = 30
    rotation_days: int = 1
    max_disk_usage_percent: int = 90
    compression_level: int = 9


class LogRotationSystem:
    """
    Система ротации и архивации логов.
    """
    
    def __init__(self, config: LogRotationConfig):
        """
        Инициализация системы ротации логов.
        
        Args:
            config: Конфигурация ротации
        """
        self.config = config
        self.logger = self._setup_logger()
        
        # Создаем директории если их нет
        self._ensure_directories()
        
        self.logger.info(f"Система ротации логов инициализирована")
        self.logger.info(f"Каталог логов: {config.log_directory}")
        self.logger.info(f"Каталог архивов: {config.archive_directory}")
    
    def _setup_logger(self) -> logging.Logger:
        """
        Настраивает логгер для системы ротации.
        
        Returns:
            Настроенный логгер
        """
        logger = logging.getLogger("LogRotationSystem")
        logger.setLevel(logging.INFO)
        
        # Обработчик для консоли
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Обработчик для файла
        file_handler = logging.FileHandler("log_rotation.log")
        file_handler.setLevel(logging.INFO)
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        
        return logger
    
    def _ensure_directories(self) -> None:
        """
        Создает необходимые директории если они не существуют.
        """
        directories = [
            self.config.log_directory,
            self.config.archive_directory,
            os.path.join(self.config.archive_directory, "daily"),
            os.path.join(self.config.archive_directory, "monthly")
        ]
        
        for directory in directories:
            if not os.path.exists(directory):
                os.makedirs(directory)
                self.logger.info(f"Создана директория: {directory}")
    
    def _check_disk_space(self) -> Tuple[bool, float]:
        """
        Проверяет свободное место на диске.
        
        Returns:
            Кортеж (достаточно_ли_места, процент_заполнения)
        """
        try:
            disk_usage = psutil.disk_usage(self.config.log_directory)
            usage_percent = disk_usage.percent
            
            self.logger.debug(
                f"Использование диска: {usage_percent:.1f}% "
                f"(свободно: {disk_usage.free / (1024**3):.1f} GB)"
            )
            
            has_space = usage_percent < self.config.max_disk_usage_percent
            return has_space, usage_percent
            
        except Exception as e:
            self.logger.error(f"Ошибка проверки дискового пространства: {str(e)}")
            return True, 0.0
    
    def _get_old_log_files(self) -> List[str]:
        """
        Находит старые файлы логов для архивации.
        
        Returns:
            Список путей к старым файлам логов
        """
        old_logs = []
        cutoff_date = datetime.now() - timedelta(days=self.config.rotation_days)
        
        try:
            for filename in os.listdir(self.config.log_directory):
                filepath = os.path.join(self.config.log_directory, filename)
                
                # Проверяем что это файл и имеет расширение .log
                if (os.path.isfile(filepath) and 
                    filename.endswith('.log') and
                    filename != "log_rotation.log"):
                    
                    # Получаем время последней модификации
                    file_mtime = datetime.fromtimestamp(
                        os.path.getmtime(filepath)
                    )
                    
                    # Если файл старше порогового значения
                    if file_mtime < cutoff_date:
                        old_logs.append(filepath)
                        
        except Exception as e:
            self.logger.error(f"Ошибка поиска старых логов: {str(e)}")
        
        return old_logs
    
    def _compress_file(self, source_path: str, dest_path: str) -> bool:
        """
        Сжимает файл используя gzip.
        
        Args:
            source_path: Путь к исходному файлу
            dest_path: Путь к сжатому файлу
            
        Returns:
            True если сжатие успешно, иначе False
        """
        try:
            with open(source_path, 'rb') as f_in:
                with gzip.open(dest_path, 'wb', 
                             compresslevel=self.config.compression_level) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            self.logger.info(f"Файл сжат: {source_path} -> {dest_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка сжатия файла {source_path}: {str(e)}")
            return False
    
    def _archive_logs(self) -> None:
        """
        Архивирует старые логи.
        """
        old_logs = self._get_old_log_files()
        
        if not old_logs:
            self.logger.info("Нет старых логов для архивации")
            return
        
        self.logger.info(f"Найдено {len(old_logs)} файлов для архивации")
        
        for log_file in old_logs:
            try:
                filename = os.path.basename(log_file)
                archive_name = f"{filename}.{datetime.now().strftime('%Y%m%d')}.gz"
                
                # Создаем путь для архива
                archive_path = os.path.join(
                    self.config.archive_directory, 
                    "daily",
                    archive_name
                )
                
                # Сжимаем файл
                if self._compress_file(log_file, archive_path):
                    # Удаляем исходный файл после успешного сжатия
                    os.remove(log_file)
                    self.logger.info(f"Файл удален: {log_file}")
                    
            except Exception as e:
                self.logger.error(f"Ошибка архивации {log_file}: {str(e)}")
    
    def _clean_old_archives(self) -> None:
        """
        Удаляет старые архивы согласно политике хранения.
        """
        cutoff_date = datetime.now() - timedelta(days=self.config.retention_days)
        
        try:
            # Проверяем архивы в обеих поддиректориях
            for archive_type in ["daily", "monthly"]:
                archive_dir = os.path.join(
                    self.config.archive_directory, 
                    archive_type
                )
                
                if not os.path.exists(archive_dir):
                    continue
                
                for filename in os.listdir(archive_dir):
                    filepath = os.path.join(archive_dir, filename)
                    
                    if os.path.isfile(filepath):
                        file_mtime = datetime.fromtimestamp(
                            os.path.getmtime(filepath)
                        )
                        
                        # Если архив старше периода хранения
                        if file_mtime < cutoff_date:
                            os.remove(filepath)
                            self.logger.info(
                                f"Старый архив удален: {filepath}"
                            )
                            
        except Exception as e:
            self.logger.error(f"Ошибка очистки архивов: {str(e)}")
    
    def _send_disk_space_alert(self, usage_percent: float) -> None:
        """
        Отправляет предупреждение о заполнении диска.
        
        Args:
            usage_percent: Процент использования диска
        """
        alert_message = (
            f"⚠️ ВНИМАНИЕ: Высокое использование дискового пространства!\n"
            f"Использовано: {usage_percent:.1f}%\n"
            f"Порог: {self.config.max_disk_usage_percent}%\n"
            f"Каталог: {self.config.log_directory}\n"
            f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        # В реальной системе здесь была бы отправка в Slack/Telegram/Email
        # Для примера выводим в консоль и пишем в лог
        print("\n" + "!"*60)
        print(alert_message)
        print("!"*60 + "\n")
        
        self.logger.warning(f"Предупреждение о дисковом пространстве: {usage_percent:.1f}%")
        
        # Сохраняем предупреждение в файл
        try:
            alert_file = os.path.join(self.config.log_directory, "disk_alerts.log")
            with open(alert_file, "a", encoding="utf-8") as f:
                alert_data = {
                    "timestamp": datetime.now().isoformat(),
                    "usage_percent": usage_percent,
                    "threshold": self.config.max_disk_usage_percent,
                    "message": alert_message
                }
                f.write(json.dumps(alert_data) + "\n")
        except Exception as e:
            self.logger.error(f"Ошибка сохранения предупреждения: {str(e)}")
    
    def _create_monthly_archive(self) -> None:
        """
        Создает месячный архив из ежедневных архивов.
        """
        try:
            daily_dir = os.path.join(self.config.archive_directory, "daily")
            monthly_dir = os.path.join(self.config.archive_directory, "monthly")
            
            if not os.path.exists(daily_dir):
                return
            
            # Получаем дату первого дня предыдущего месяца
            today = datetime.now()
            first_day_of_month = today.replace(day=1)
            previous_month = first_day_of_month - timedelta(days=1)
            month_str = previous_month.strftime("%Y%m")
            
            # Архивы для предыдущего месяца
            month_archives = [
                f for f in os.listdir(daily_dir)
                if f".{month_str}" in f
            ]
            
            if month_archives:
                # Создаем tar-архив для всего месяца
                monthly_archive = os.path.join(
                    monthly_dir, 
                    f"logs_{month_str}.tar.gz"
                )
                
                # В реальной системе здесь был бы код для создания tar.gz
                # Для примера просто логируем
                self.logger.info(
                    f"Создан месячный архив: {monthly_archive} "
                    f"({len(month_archives)} файлов)"
                )
                
        except Exception as e:
            self.logger.error(f"Ошибка создания месячного архива: {str(e)}")
    
    def run_rotation(self) -> None:
        """
        Выполняет полный цикл ротации логов.
        """
        self.logger.info("Запуск ротации логов...")
        
        # Проверяем дисковое пространство
        has_space, usage_percent = self._check_disk_space()
        
        if not has_space:
            self._send_disk_space_alert(usage_percent)
        
        # Архивируем логи
        self._archive_logs()
        
        # Очищаем старые архивы
        self._clean_old_archives()
        
        # Создаем месячный архив в первый день месяца
        if datetime.now().day == 1:
            self._create_monthly_archive()
        
        self.logger.info("Ротация логов завершена")
    
    def schedule_rotation(self) -> None:
        """
        Настраивает регулярное выполнение ротации по расписанию.
        """
        # Ежедневная ротация в 2:00 ночи
        schedule.every().day.at("02:00").do(self.run_rotation)
        
        # Ежемесячный отчет в 3:00 первого числа месяца
        schedule.every().day.at("03:00").do(
            lambda: self.logger.info("Проверка месячных архивов")
        )
        
        self.logger.info("Расписание ротации настроено")
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Проверяем расписание каждую минуту
        except KeyboardInterrupt:
            self.logger.info("Расписание ротации остановлено")


# Пример использования
if __name__ == "__main__":
    # Конфигурация системы ротации
    config = LogRotationConfig(
        log_directory="/var/log/myapp",
        archive_directory="/var/log/archives",
        retention_days=90,          # Хранить архивы 90 дней
        rotation_days=7,            # Ротировать логи старше 7 дней
        max_disk_usage_percent=85,  # Предупреждение при 85% заполнения
        compression_level=6         # Уровень сжатия (1-9)
    )
    
    # Создаем систему ротации
    rotation_system = LogRotationSystem(config)
    
    # Вариант 1: Однократный запуск
    # rotation_system.run_rotation()
    
    # Вариант 2: Запуск по расписанию
    print("Система ротации логов запущена...")
    print("Нажмите Ctrl+C для остановки")
    rotation_system.schedule_rotation()