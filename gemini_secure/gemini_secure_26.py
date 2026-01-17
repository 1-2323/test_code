import dateparser
import re
from datetime import datetime
from typing import Optional, List, Final


class DateValidationError(Exception):
    """Исключение при передаче некорректного или опасного формата даты."""
    pass


class DateToolkit:
    """
    Библиотека-обертка для безопасной обработки дат.
    Обеспечивает предварительную фильтрацию данных перед парсингом.
    """

    # Ограничение длины строки для предотвращения перегрузки парсера (DoS)
    MAX_INPUT_LENGTH: Final[int] = 50

    # Белый список разрешенных символов (цифры, буквы, знаки препинания для дат)
    # Запрещает использование сложных структур или скриптов внутри строки
    ALLOWED_CHARS_PATTERN: Final[re.Pattern] = re.compile(r"^[a-zA-Z0-9\s\.,:/-]+$")

    # Предопределенные строгие форматы для первичной проверки
    STRICT_FORMATS: Final[List[str]] = [
        "%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", 
        "%Y-%m-%dT%H:%M:%S", "%d %b %Y"
    ]

    @classmethod
    def _pre_validate(cls, date_string: str) -> None:
        """
        Выполняет жесткую проверку входящей строки.
        """
        # 1. Проверка на пустую строку
        if not date_string or not date_string.strip():
            raise DateValidationError("Date string cannot be empty.")

        # 2. Проверка длины (защита от Resource Exhaustion)
        if len(date_string) > cls.MAX_INPUT_LENGTH:
            raise DateValidationError(f"Input exceeds maximum length of {cls.MAX_INPUT_LENGTH} characters.")

        # 3. Проверка состава (защита от инъекций и ReDoS в сторонних библиотеках)
        if not cls.ALLOWED_CHARS_PATTERN.match(date_string):
            raise DateValidationError("Input contains forbidden characters.")

    @classmethod
    def parse(cls, date_string: str, settings: Optional[dict] = None) -> datetime:
        """
        Безопасно преобразует строку в объект datetime.
        
        :param date_string: Входящая строка с датой.
        :param settings: Дополнительные настройки для dateparser.
        :return: Объект datetime.
        """
        # Шаг 1: Предварительная фильтрация
        cls._pre_validate(date_string)

        # Шаг 2: Попытка быстрого парсинга через строгие форматы (оптимизация)
        for fmt in cls.STRICT_FORMATS:
            try:
                return datetime.strptime(date_string, fmt)
            except ValueError:
                continue

        # Шаг 3: Обращение к внешнему парсеру (только после валидации)
        # Отключаем использование fuzzy-логики, если нужна максимальная строгость
        try:
            parsed_date = dateparser.parse(
                date_string, 
                settings=settings or {"STRICT_PARSING": True, "RETURN_AS_TIMEZONE_AWARE": False}
            )
            
            if parsed_date is None:
                raise DateValidationError(f"Format of '{date_string}' is not recognized.")
                
            return parsed_date

        except Exception as e:
            # Оборачиваем ошибки сторонней библиотеки в наш тип
            raise DateValidationError(f"External parsing error: {str(e)}")

    @classmethod
    def is_valid_date(cls, date_string: str) -> bool:
        """Проверяет, является ли строка валидной датой без генерации исключения."""
        try:
            cls.parse(date_string)
            return True
        except DateValidationError:
            return False


# --- Пример использования ---
# try:
#     dt = DateToolkit.parse("2026-01-17")
#     print(f"Parsed successfully: {dt}")
#     
#     # Попытка передать опасную или слишком длинную строку
#     DateToolkit.parse("1" * 100) # Вызовет DateValidationError
# except DateValidationError as err:
#     print(f"Validation failed: {err}")