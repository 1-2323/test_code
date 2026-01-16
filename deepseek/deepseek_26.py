from datetime import datetime
from typing import Optional, Union, List
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
import pytz


class DateToolkit:
    """Библиотека-обертка для работы с датами с использованием dateutil и pytz."""
    
    # Поддерживаемые форматы для парсинга
    SUPPORTED_FORMATS = [
        '%Y-%m-%d',
        '%d.%m.%Y',
        '%m/%d/%Y',
        '%Y-%m-%d %H:%M:%S',
        '%d-%b-%Y',
        '%Y%m%d'
    ]
    
    def __init__(self, timezone: str = 'UTC'):
        """
        Инициализация DateToolkit.
        
        Args:
            timezone: Часовой пояс по умолчанию (по умолчанию 'UTC')
        """
        self.timezone = pytz.timezone(timezone)
    
    def parse_date(self, date_string: str, fmt: Optional[str] = None) -> Optional[datetime]:
        """
        Парсит строку с датой в объект datetime.
        
        Args:
            date_string: Строка с датой
            fmt: Специфический формат для парсинга (если None, используется автоопределение)
        
        Returns:
            Объект datetime или None если парсинг не удался
        """
        try:
            if fmt:
                # Парсинг с указанным форматом
                dt = datetime.strptime(date_string, fmt)
                return self.timezone.localize(dt) if dt.tzinfo is None else dt
            else:
                # Автоматический парсинг с помощью dateutil
                dt = date_parser.parse(date_string)
                if dt.tzinfo is None:
                    return self.timezone.localize(dt)
                return dt
        except (ValueError, date_parser.ParserError) as e:
            print(f"Ошибка парсинга даты '{date_string}': {e}")
            return None
    
    def validate_date_string(self, date_string: str, fmt: Optional[str] = None) -> bool:
        """
        Проверяет валидность строки с датой.
        
        Args:
            date_string: Строка для валидации
            fmt: Ожидаемый формат (если None, проверяются все поддерживаемые форматы)
        
        Returns:
            True если строка валидна, иначе False
        """
        if fmt:
            return self._validate_with_format(date_string, fmt)
        else:
            # Проверяем все поддерживаемые форматы
            for supported_fmt in self.SUPPORTED_FORMATS:
                if self._validate_with_format(date_string, supported_fmt):
                    return True
            # Пробуем автоопределение через dateutil
            try:
                date_parser.parse(date_string)
                return True
            except (ValueError, date_parser.ParserError):
                return False
    
    def _validate_with_format(self, date_string: str, fmt: str) -> bool:
        """Валидация с использованием конкретного формата."""
        try:
            datetime.strptime(date_string, fmt)
            return True
        except ValueError:
            return False
    
    def format_date(self, dt: datetime, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
        """
        Форматирует объект datetime в строку.
        
        Args:
            dt: Объект datetime
            fmt: Формат вывода
        
        Returns:
            Отформатированная строка
        """
        return dt.strftime(fmt)
    
    def add_time_interval(self, dt: datetime, 
                         days: int = 0, 
                         months: int = 0, 
                         years: int = 0) -> datetime:
        """
        Добавляет временной интервал к дате.
        
        Args:
            dt: Исходная дата
            days: Количество дней для добавления
            months: Количество месяцев для добавления
            years: Количество лет для добавления
        
        Returns:
            Новая дата с добавленным интервалом
        """
        return dt + relativedelta(days=days, months=months, years=years)
    
    def is_future_date(self, dt: datetime) -> bool:
        """Проверяет, является ли дата будущей."""
        return dt > datetime.now(self.timezone)
    
    def get_current_date(self) -> datetime:
        """Возвращает текущую дату и время с учетом часового пояса."""
        return datetime.now(self.timezone)


# Пример использования
if __name__ == "__main__":
    # Создаем экземпляр библиотеки
    date_toolkit = DateToolkit(timezone='Europe/Moscow')
    
    # Парсинг дат
    date1 = date_toolkit.parse_date("2024-12-31")
    date2 = date_toolkit.parse_date("31.12.2024", fmt="%d.%m.%Y")
    
    # Валидация
    print(date_toolkit.validate_date_string("2024-12-31"))  # True
    print(date_toolkit.validate_date_string("invalid-date"))  # False
    
    # Форматирование
    if date1:
        print(date_toolkit.format_date(date1, "%d %B %Y"))