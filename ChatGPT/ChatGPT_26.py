from datetime import date, datetime
from typing import Iterable, Optional

from dateutil import parser
from dateutil.parser import ParserError


# =========================
# Исключения
# =========================

class DateToolkitError(Exception):
    """
    Базовое исключение библиотеки DateToolkit.
    """


class InvalidDateFormatError(DateToolkitError):
    """
    Выбрасывается при невозможности распарсить дату.
    """


class DateValidationError(DateToolkitError):
    """
    Выбрасывается при логически некорректной дате.
    """


# =========================
# Конфигурация
# =========================

class DateToolkitConfig:
    """
    Конфигурация допустимых форматов и правил парсинга.
    """

    def __init__(
        self,
        allowed_formats: Optional[Iterable[str]] = None,
        day_first: bool = False,
        year_first: bool = True,
    ) -> None:
        self.allowed_formats = allowed_formats
        self.day_first = day_first
        self.year_first = year_first


# =========================
# Основной сервис
# =========================

class DateToolkit:
    """
    Универсальная библиотека для парсинга и валидации дат.
    """

    def __init__(
        self,
        config: Optional[DateToolkitConfig] = None,
    ) -> None:
        self._config = config or DateToolkitConfig()

    # =========================
    # Public API
    # =========================

    def parse_datetime(self, value: str) -> datetime:
        """
        Парсит строку в datetime.

        :raises InvalidDateFormatError
        """
        self._validate_input(value)

        try:
            parsed = parser.parse(
                value,
                dayfirst=self._config.day_first,
                yearfirst=self._config.year_first,
            )
        except ParserError as exc:
            raise InvalidDateFormatError(
                f"Unable to parse datetime: '{value}'"
            ) from exc

        return parsed

    def parse_date(self, value: str) -> date:
        """
        Парсит строку в date (без времени).
        """
        parsed_datetime = self.parse_datetime(value)
        return parsed_datetime.date()

    def is_valid(self, value: str) -> bool:
        """
        Проверяет, является ли строка валидной датой.
        """
        try:
            self.parse_datetime(value)
            return True
        except DateToolkitError:
            return False

    def parse_with_format(self, value: str, fmt: str) -> datetime:
        """
        Парсит дату по строго заданному формату.
        """
        self._validate_input(value)

        try:
            return datetime.strptime(value, fmt)
        except ValueError as exc:
            raise InvalidDateFormatError(
                f"Date '{value}' does not match format '{fmt}'"
            ) from exc

    # =========================
    # Валидация
    # =========================

    def _validate_input(self, value: str) -> None:
        """
        Выполняет базовую валидацию входной строки.
        """
        if not value:
            raise DateValidationError("Date string is empty")

        if not isinstance(value, str):
            raise DateValidationError("Date value must be a string")

        if len(value) > 100:
            raise DateValidationError("Date string is too long")


# =========================
# Пример использования
# =========================

if __name__ == "__main__":
    toolkit = DateToolkit()

    examples = [
        "2025-01-10",
        "10 Jan 2025",
        "2025/01/10 15:30",
        "invalid-date",
    ]

    for example in examples:
        if toolkit.is_valid(example):
            print(example, "→", toolkit.parse_datetime(example))
        else:
            print(example, "→ invalid")
