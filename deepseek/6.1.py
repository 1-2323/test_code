import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, Union
import dateutil.parser
from dateutil.relativedelta import relativedelta


class DateUtility:
    """
    Утилита для парсинга и форматирования дат из пользовательского ввода.
    Основана на библиотеке python-dateutil.
    """
    
    # Поддерживаемые форматы дат для парсинга
    DATE_FORMATS = [
        '%Y-%m-%d',        # 2023-12-31
        '%d.%m.%Y',        # 31.12.2023
        '%d/%m/%Y',        # 31/12/2023
        '%Y/%m/%d',        # 2023/12/31
        '%d-%m-%Y',        # 31-12-2023
        '%m/%d/%Y',        # 12/31/2023 (US format)
        '%d %B %Y',        # 31 December 2023
        '%B %d, %Y',       # December 31, 2023
        '%d %b %Y',        # 31 Dec 2023
        '%b %d, %Y',       # Dec 31, 2023
        '%Y%m%d',          # 20231231
        '%d.%m.%y',        # 31.12.23
        '%d/%m/%y',        # 31/12/23
    ]
    
    # Регулярные выражения для относительных дат
    RELATIVE_PATTERNS = {
        'сегодня': 'today',
        'today': 'today',
        'вчера': 'yesterday',
        'yesterday': 'yesterday',
        'завтра': 'tomorrow',
        'tomorrow': 'tomorrow',
        'позавчера': 'day_before_yesterday',
        'послезавтра': 'day_after_tomorrow',
    }
    
    # Паттерны для относительных временных интервалов
    RELATIVE_INTERVAL_PATTERNS = [
        (r'(\d+)\s*(день|дня|дней|day|days)\s*назад', 'days_ago'),
        (r'(\d+)\s*(день|дня|дней|day|days)\s*вперед', 'days_forward'),
        (r'(\d+)\s*(недел[юяь]|недели|недель|week|weeks)\s*назад', 'weeks_ago'),
        (r'(\d+)\s*(недел[юяь]|недели|недель|week|weeks)\s*вперед', 'weeks_forward'),
        (r'(\d+)\s*(месяц|месяца|месяцев|month|months)\s*назад', 'months_ago'),
        (r'(\d+)\s*(месяц|месяца|месяцев|month|months)\s*вперед', 'months_forward'),
        (r'(\d+)\s*(год|года|лет|year|years)\s*назад', 'years_ago'),
        (r'(\d+)\s*(год|года|лет|year|years)\s*вперед', 'years_forward'),
    ]
    
    def __init__(self, default_timezone=None, language='ru'):
        """
        Инициализация DateUtility.
        
        Args:
            default_timezone: Часовой пояс по умолчанию
            language: Язык для парсинга ('ru' или 'en')
        """
        self.default_timezone = default_timezone
        self.language = language
        self._compiled_interval_patterns = [
            (re.compile(pattern, re.IGNORECASE), handler)
            for pattern, handler in self.RELATIVE_INTERVAL_PATTERNS
        ]
    
    def parse_date(self, date_input: str, fuzzy: bool = True) -> Optional[datetime]:
        """
        Парсит строку с датой в объект datetime.
        
        Args:
            date_input: Строка с датой для парсинга
            fuzzy: Разрешить нечеткий парсинг dateutil
            
        Returns:
            Объект datetime или None если парсинг не удался
        """
        if not date_input or not isinstance(date_input, str):
            return None
        
        # Приводим к нижнему регистру для обработки
        normalized_input = date_input.strip().lower()
        
        # Пытаемся обработать относительные даты
        date_obj = self._parse_relative_date(normalized_input)
        if date_obj:
            return date_obj
        
        # Пытаемся обработать относительные интервалы
        date_obj = self._parse_relative_interval(normalized_input)
        if date_obj:
            return date_obj
        
        # Пытаемся парсить стандартные форматы
        date_obj = self._parse_standard_formats(normalized_input)
        if date_obj:
            return date_obj
        
        # Используем dateutil для нечеткого парсинга
        try:
            return dateutil.parser.parse(date_input, fuzzy=fuzzy, dayfirst=self.language == 'ru')
        except (ValueError, OverflowError, TypeError):
            return None
    
    def _parse_relative_date(self, date_input: str) -> Optional[datetime]:
        """Парсит относительные даты (сегодня, вчера и т.д.)."""
        today = datetime.now()
        
        if date_input in self.RELATIVE_PATTERNS:
            mapping = {
                'today': today,
                'yesterday': today - timedelta(days=1),
                'tomorrow': today + timedelta(days=1),
                'day_before_yesterday': today - timedelta(days=2),
                'day_after_tomorrow': today + timedelta(days=2),
            }
            
            english_key = self.RELATIVE_PATTERNS[date_input]
            if english_key in mapping:
                return mapping[english_key].replace(hour=0, minute=0, second=0, microsecond=0)
        
        return None
    
    def _parse_relative_interval(self, date_input: str) -> Optional[datetime]:
        """Парсит относительные временные интервалы."""
        today = datetime.now()
        
        for pattern, handler in self._compiled_interval_patterns:
            match = pattern.match(date_input)
            if match:
                value = int(match.group(1))
                
                if handler == 'days_ago':
                    return today - timedelta(days=value)
                elif handler == 'days_forward':
                    return today + timedelta(days=value)
                elif handler == 'weeks_ago':
                    return today - timedelta(weeks=value)
                elif handler == 'weeks_forward':
                    return today + timedelta(weeks=value)
                elif handler == 'months_ago':
                    return today - relativedelta(months=value)
                elif handler == 'months_forward':
                    return today + relativedelta(months=value)
                elif handler == 'years_ago':
                    return today - relativedelta(years=value)
                elif handler == 'years_forward':
                    return today + relativedelta(years=value)
        
        return None
    
    def _parse_standard_formats(self, date_input: str) -> Optional[datetime]:
        """Парсит стандартные форматы дат."""
        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(date_input, fmt)
            except ValueError:
                continue
        return None
    
    def format_date(self, date_obj: datetime, format_str: str = '%Y-%m-%d') -> str:
        """
        Форматирует объект datetime в строку.
        
        Args:
            date_obj: Объект datetime для форматирования
            format_str: Строка формата (по умолчанию YYYY-MM-DD)
            
        Returns:
            Отформатированная строка с датой
        """
        if not isinstance(date_obj, datetime):
            raise ValueError("date_obj должен быть объектом datetime")
        
        return date_obj.strftime(format_str)
    
    def humanize_date(self, date_obj: datetime, language: str = None) -> str:
        """
        Преобразует дату в человекочитаемый формат.
        
        Args:
            date_obj: Объект datetime
            language: Язык вывода ('ru' или 'en')
            
        Returns:
            Человекочитаемое представление даты
        """
        lang = language or self.language
        
        if lang == 'ru':
            month_names = [
                'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
            ]
            return f"{date_obj.day} {month_names[date_obj.month - 1]} {date_obj.year}"
        else:
            month_names = [
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ]
            return f"{month_names[date_obj.month - 1]} {date_obj.day}, {date_obj.year}"
    
    def extract_date_range(self, text: str) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Извлекает диапазон дат из текста.
        
        Args:
            text: Текст, содержащий информацию о диапазоне дат
            
        Returns:
            Кортеж (начальная дата, конечная дата)
        """
        # Ищем паттерны диапазонов
        patterns = [
            # С ... по ...
            (r'с\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+по\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})', 'ru_range'),
            # from ... to ...
            (r'from\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+to\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})', 'en_range'),
            # ... - ...
            (r'(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*-\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})', 'dash_range'),
        ]
        
        for pattern, pattern_type in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start_date = self.parse_date(match.group(1))
                end_date = self.parse_date(match.group(2))
                
                if start_date and end_date:
                    return start_date, end_date
        
        return None, None
    
    def is_valid_date(self, date_str: str) -> bool:
        """
        Проверяет, является ли строка валидной датой.
        
        Args:
            date_str: Строка для проверки
            
        Returns:
            True если строка может быть распарсена как дата
        """
        return self.parse_date(date_str) is not None
    
    def get_date_components(self, date_obj: datetime) -> dict:
        """
        Возвращает компоненты даты в виде словаря.
        
        Args:
            date_obj: Объект datetime
            
        Returns:
            Словарь с компонентами даты
        """
        return {
            'year': date_obj.year,
            'month': date_obj.month,
            'day': date_obj.day,
            'hour': date_obj.hour,
            'minute': date_obj.minute,
            'second': date_obj.second,
            'weekday': date_obj.weekday(),  # 0 = Monday
            'isoweekday': date_obj.isoweekday(),  # 1 = Monday
            'isoformat': date_obj.isoformat(),
        }
    
    def add_time_interval(self, date_obj: datetime, interval: str) -> datetime:
        """
        Добавляет временной интервал к дате.
        
        Args:
            date_obj: Исходная дата
            interval: Интервал в формате "1 day", "2 weeks", "3 months" и т.д.
            
        Returns:
            Новая дата
        """
        if not interval:
            return date_obj
        
        interval = interval.lower()
        today = datetime.now()
        
        # Парсим интервал
        interval_patterns = [
            (r'(\d+)\s*(день|дня|дней|day|days)', 'days'),
            (r'(\d+)\s*(недел[юяь]|недели|недель|week|weeks)', 'weeks'),
            (r'(\d+)\s*(месяц|месяца|месяцев|month|months)', 'months'),
            (r'(\d+)\s*(год|года|лет|year|years)', 'years'),
            (r'(\d+)\s*(час|часа|часов|hour|hours)', 'hours'),
            (r'(\d+)\s*(минут[аыу]|minute|minutes)', 'minutes'),
        ]
        
        for pattern, unit in interval_patterns:
            match = re.match(pattern, interval)
            if match:
                value = int(match.group(1))
                
                if unit == 'days':
                    return date_obj + timedelta(days=value)
                elif unit == 'weeks':
                    return date_obj + timedelta(weeks=value)
                elif unit == 'months':
                    return date_obj + relativedelta(months=value)
                elif unit == 'years':
                    return date_obj + relativedelta(years=value)
                elif unit == 'hours':
                    return date_obj + timedelta(hours=value)
                elif unit == 'minutes':
                    return date_obj + timedelta(minutes=value)
        
        return date_obj
    
    @staticmethod
    def now() -> datetime:
        """Возвращает текущую дату и время."""
        return datetime.now()
    
    @staticmethod
    def today() -> datetime:
        """Возвращает начало текущего дня."""
        now = datetime.now()
        return datetime(now.year, now.month, now.day)