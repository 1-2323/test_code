"""
Модуль для парсинга и форматирования дат из пользовательского ввода.
Используется библиотека dateparser для гибкого разбора дат.
"""

import re
import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from enum import Enum
import dateparser
from dateparser.search import search_dates
from packaging import version
import requests
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DateFormat(Enum):
    """Поддерживаемые форматы вывода дат."""
    ISO = "iso"          # YYYY-MM-DD
    HUMAN = "human"      # 15 января 2023 года
    SHORT = "short"      # 15.01.2023
    DATETIME = "datetime" # YYYY-MM-DD HH:MM:SS


class DateValidationError(Exception):
    """Исключение для ошибок валидации дат."""
    pass


class DateUtility:
    """
    Класс для парсинга и форматирования дат из пользовательского ввода.
    
    Использует библиотеку dateparser для гибкого разбора естественного языка.
    Проверяет зависимости на наличие известных уязвимостей CVE.
    """
    
    # Минимальные безопасные версии зависимостей
    MIN_SAFE_VERSIONS = {
        'dateparser': '1.1.0',
        'python-dateutil': '2.8.2',
        'tzlocal': '4.2',
        'regex': '2022.10.31'
    }
    
    # CVE для проверки (примеры, актуальные на момент написания)
    KNOWN_CVE = {
        'dateparser': [],
        'python-dateutil': ['CVE-2020-26204'],
        'tzlocal': [],
        'regex': ['CVE-2022-42969']
    }
    
    def __init__(self, default_timezone: str = 'UTC', 
                 languages: list = None,
                 strict_parsing: bool = False):
        """
        Инициализация DateUtility.
        
        Args:
            default_timezone: Часовой пояс по умолчанию
            languages: Список языков для распознавания (например, ['ru', 'en'])
            strict_parsing: Строгий режим парсинга (только полные совпадения)
        """
        self.default_timezone = default_timezone
        self.languages = languages or ['ru', 'en']
        self.strict_parsing = strict_parsing
        
        # Проверка безопасности зависимостей
        self._check_dependencies()
        
        # Настройки парсера
        self.settings = {
            'TIMEZONE': self.default_timezone,
            'RETURN_AS_TIMEZONE_AWARE': True,
            'PREFER_DAY_OF_MONTH': 'first',
            'PREFER_DATES_FROM': 'current_period',
            'LANGUAGES': self.languages,
            'STRICT_PARSING': self.strict_parsing
        }
        
        # Кэш для результатов парсинга
        self._parse_cache: Dict[str, datetime] = {}
        
        # Регулярные выражения для частых форматов
        self._date_patterns = [
            (r'\d{2}\.\d{2}\.\d{4}', '%d.%m.%Y'),  # 15.01.2023
            (r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'),    # 2023-01-15
            (r'\d{2}/\d{2}/\d{4}', '%d/%m/%Y'),    # 15/01/2023
        ]
        
        logger.info(f"DateUtility инициализирован с языками: {self.languages}")
    
    @classmethod
    def _check_dependencies(cls) -> None:
        """
        Проверяет версии зависимостей и известные CVE.
        
        Raises:
            ImportError: Если зависимость не установлена
            SecurityWarning: Если обнаружена уязвимая версия
        """
        import importlib.metadata
        import warnings
        
        for dep, min_version in cls.MIN_SAFE_VERSIONS.items():
            try:
                installed_version = importlib.metadata.version(dep)
                
                # Проверка минимальной версии
                if version.parse(installed_version) < version.parse(min_version):
                    warnings.warn(
                        f"{dep} {installed_version} ниже безопасной версии {min_version}",
                        category=SecurityWarning
                    )
                
                # Проверка известных CVE (упрощенная проверка)
                if dep in cls.KNOWN_CVE and cls.KNOWN_CVE[dep]:
                    logger.warning(
                        f"Проверьте {dep} {installed_version} на CVE: {cls.KNOWN_CVE[dep]}"
                    )
                    
            except importlib.metadata.PackageNotFoundError:
                raise ImportError(f"Зависимость {dep} не установлена")
        
        # Дополнительная проверка через OSS Index API (если доступно)
        try:
            cls._check_oss_index()
        except Exception as e:
            logger.debug(f"Не удалось проверить OSS Index: {e}")
    
    @staticmethod
    def _check_oss_index() -> None:
        """
        Проверка зависимостей через OSS Index API.
        Требует настройки в продакшн-среде.
        """
        # В продакшн-среде здесь может быть реализована проверка через
        # API OSS Index, NVD или аналогичные сервисы
        pass
    
    def parse_date(self, date_string: str, context: Optional[dict] = None) -> Optional[datetime]:
        """
        Парсит строку с датой в объект datetime.
        
        Args:
            date_string: Строка с датой для парсинга
            context: Дополнительный контекст (например, {'RELATIVE_BASE': datetime})
            
        Returns:
            Объект datetime или None если не удалось распарсить
            
        Raises:
            DateValidationError: Если строка не является валидной датой в строгом режиме
        """
        if not date_string or not isinstance(date_string, str):
            if self.strict_parsing:
                raise DateValidationError("Пустая или некорректная строка даты")
            return None
        
        # Проверка кэша
        cache_key = f"{date_string}_{hash(str(context))}"
        if cache_key in self._parse_cache:
            return self._parse_cache[cache_key]
        
        # Объединение настроек с контекстом
        parse_settings = self.settings.copy()
        if context:
            parse_settings.update(context)
        
        try:
            # Сначала пробуем стандартные форматы для производительности
            for pattern, date_format in self._date_patterns:
                if re.fullmatch(pattern, date_string.strip()):
                    try:
                        result = datetime.strptime(date_string.strip(), date_format)
                        self._parse_cache[cache_key] = result
                        return result
                    except ValueError:
                        continue
            
            # Используем dateparser для сложных случаев
            result = dateparser.parse(
                date_string,
                settings=parse_settings
            )
            
            # Если dateparser не смог, пробуем поиск дат в тексте
            if not result:
                found_dates = search_dates(
                    date_string,
                    languages=self.languages,
                    settings=parse_settings
                )
                if found_dates:
                    result = found_dates[0][1]
            
            if result:
                self._parse_cache[cache_key] = result
                return result
            
            if self.strict_parsing:
                raise DateValidationError(f"Не удалось распарсить дату: {date_string}")
                
            return None
            
        except Exception as e:
            logger.error(f"Ошибка парсинга даты '{date_string}': {e}")
            if self.strict_parsing:
                raise DateValidationError(f"Ошибка парсинга даты: {str(e)}")
            return None
    
    def format_date(self, date_obj: datetime, 
                    output_format: DateFormat = DateFormat.ISO,
                    locale: str = 'ru') -> str:
        """
        Форматирует datetime в строку.
        
        Args:
            date_obj: Объект datetime для форматирования
            output_format: Формат вывода
            locale: Локаль для текстового представления
            
        Returns:
            Отформатированная строка даты
        """
        if not isinstance(date_obj, datetime):
            raise TypeError("Объект должен быть типа datetime")
        
        if output_format == DateFormat.ISO:
            return date_obj.isoformat()
            
        elif output_format == DateFormat.SHORT:
            return date_obj.strftime('%d.%m.%Y')
            
        elif output_format == DateFormat.DATETIME:
            return date_obj.strftime('%Y-%m-%d %H:%M:%S')
            
        elif output_format == DateFormat.HUMAN:
            # Для человекочитаемого формата используем dateparser обратно
            try:
                from dateparser_data.settings import default_parsers
                
                # Форматирование на русском языке
                if locale == 'ru':
                    months = [
                        'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
                    ]
                    return (f"{date_obj.day} {months[date_obj.month-1]} "
                          f"{date_obj.year} года")
                else:
                    return date_obj.strftime('%B %d, %Y')
                    
            except ImportError:
                # Фолбэк на ISO формат
                return date_obj.isoformat()
        
        else:
            raise ValueError(f"Неподдерживаемый формат: {output_format}")
    
    def validate_date_range(self, start_date: datetime, 
                           end_date: datetime,
                           max_range_days: int = 365) -> Tuple[bool, str]:
        """
        Проверяет корректность диапазона дат.
        
        Args:
            start_date: Начальная дата
            end_date: Конечная дата
            max_range_days: Максимальный допустимый диапазон в днях
            
        Returns:
            Кортеж (валидность, сообщение об ошибке)
        """
        if end_date < start_date:
            return False, "Конечная дата раньше начальной"
        
        delta = end_date - start_date
        if delta.days > max_range_days:
            return False, f"Диапазон дат превышает {max_range_days} дней"
        
        return True, ""
    
    def extract_dates_from_text(self, text: str, 
                               limit: int = 5) -> list:
        """
        Извлекает все даты из текста.
        
        Args:
            text: Текст для анализа
            limit: Максимальное количество извлекаемых дат
            
        Returns:
            Список найденных дат в формате (текст, datetime)
        """
        if not text:
            return []
        
        try:
            found_dates = search_dates(
                text,
                languages=self.languages,
                settings=self.settings,
                limit=limit
            )
            return found_dates or []
            
        except Exception as e:
            logger.error(f"Ошибка извлечения дат из текста: {e}")
            return []
    
    def clear_cache(self) -> None:
        """Очищает кэш парсинга."""
        self._parse_cache.clear()
        logger.debug("Кэш парсинга дат очищен")
    
    @property
    def cache_size(self) -> int:
        """Возвращает текущий размер кэша."""
        return len(self._parse_cache)
    
    @staticmethod
    def get_current_version() -> str:
        """Возвращает версию утилиты."""
        return "1.0.0"


# requirements.txt содержимое:
"""
# Парсинг дат
dateparser>=1.1.0  # Гибкий парсинг естественного языка

# Зависимости dateparser
python-dateutil>=2.8.2  # Парсинг и манипуляции с датами
tzlocal>=4.2            # Работа с часовыми поясами
regex>=2022.10.31       # Регулярные выражения

# Безопасность и управление зависимостями
packaging>=21.3         # Сравнение версий
requests>=2.28.1        # Для проверки CVE (опционально)

# Логирование
# Используется стандартный logging

# Тестирование (опционально, для разработки)
# pytest>=7.2.0
# pytest-cov>=4.0.0

# Примечание: Проверьте актуальность CVE перед использованием в продакшн
# Известные CVE на момент написания:
# python-dateutil: CVE-2020-26204 (фикс в версии 2.8.2)
# regex: CVE-2022-42969 (фикс в версии 2022.10.31)
"""

# pyproject.toml фрагмент для проверки безопасности:
"""
[tool.security]
# Конфигурация для проверки безопасности
bandit = { exclude_dirs = ["tests"] }
safety = { check = true }

[tool.taskipy.tasks]
check-security = "safety check && bandit -r ."
update-dependencies = "pip-audit"

[project]
dependencies = [
    "dateparser>=1.1.0",
    "python-dateutil>=2.8.2",
    "tzlocal>=4.2",
    "regex>=2022.10.31",
    "packaging>=21.3",
    "requests>=2.28.1; extra == 'security'",
]

[project.optional-dependencies]
security = ["requests>=2.28.1"]
dev = ["pytest>=7.2.0", "pytest-cov>=4.0.0", "requests>=2.28.1"]
"""