import re
from datetime import datetime, date
from typing import Optional

from dateutil import parser


# =========================
# EXCEPTIONS
# =========================

class DateToolkitError(Exception):
    pass


class InvalidDateFormatError(DateToolkitError):
    pass


class DateInputTooLongError(DateToolkitError):
    pass


# =========================
# DATE TOOLKIT
# =========================

class DateToolkit:
    """
    Безопасная библиотека-обертка для работы с датами.
    Выполняет строгую валидацию входных строк перед парсингом.
    """

    # Жесткий лимит длины входной строки
    MAX_INPUT_LENGTH: int = 32

    # Разрешенные форматы (строгая предварительная проверка)
    _ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
    _EU_DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
    _US_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

    @classmethod
    def parse_date(cls, value: str) -> date:
        """
        Парсит дату без времени.
        """
        dt = cls._parse(value)
        return dt.date()

    @classmethod
    def parse_datetime(cls, value: str) -> datetime:
        """
        Парсит дату и время.
        """
        return cls._parse(value)

    @classmethod
    def _parse(cls, value: str) -> datetime:
        """
        Общая логика безопасного парсинга.
        """
        cls._validate_length(value)
        cls._validate_format(value)

        try:
            return parser.parse(
                value,
                fuzzy=False,
            )
        except (ValueError, OverflowError) as exc:
            raise InvalidDateFormatError(
                "Невозможно распознать дату"
            ) from exc

    @classmethod
    def _validate_length(cls, value: str) -> None:
        """
        Проверяет длину входной строки.
        """
        if not isinstance(value, str):
            raise InvalidDateFormatError("Ожидается строка")

        if len(value) > cls.MAX_INPUT_LENGTH:
            raise DateInputTooLongError(
                f"Длина строки превышает {cls.MAX_INPUT_LENGTH} символов"
            )

    @classmethod
    def _validate_format(cls, value: str) -> None:
        """
        Проверяет формат даты по белому списку шаблонов.
        """
        if (
            cls._ISO_DATE.match(value)
            or cls._ISO_DATETIME.match(value)
            or cls._EU_DATE.match(value)
            or cls._US_DATE.match(value)
        ):
            return

        raise InvalidDateFormatError(
            "Формат даты не разрешён"
        )


# =========================
# PUBLIC API
# =========================

__all__ = [
    "DateToolkit",
    "DateToolkitError",
    "InvalidDateFormatError",
    "DateInputTooLongError",
]
