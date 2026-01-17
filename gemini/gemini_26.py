import dateparser
from datetime import datetime, timezone
from typing import Optional, Dict, Union

class DateToolkit:
    """
    Библиотека-обертка для продвинутой работы с датами.
    Обеспечивает парсинг произвольных форматов и валидацию.
    """

    @staticmethod
    def parse(date_string: str, settings: Optional[Dict] = None) -> Optional[datetime]:
        """
        Парсит строку в объект datetime. 
        Поддерживает форматы: '2026-01-17', '10.05.2025', 'вчера', '2 hours ago'.
        """
        default_settings = {
            'PREFER_DATES_FROM': 'future',
            'TIMEZONE': 'UTC',
            'RETURN_AS_TIMEZONE_AWARE': True
        }
        if settings:
            default_settings.update(settings)

        return dateparser.parse(date_string, settings=default_settings)

    @classmethod
    def is_valid(cls, date_string: str) -> bool:
        """Проверяет, является ли строка валидной датой."""
        return cls.parse(date_string) is not None

    @classmethod
    def format_to_iso(cls, date_string: str) -> Optional[str]:
        """Конвертирует любую входящую дату в стандарт ISO 8601."""
        dt = cls.parse(date_string)
        return dt.isoformat() if dt else None

    @staticmethod
    def get_relative_diff(date_string: str) -> Optional[int]:
        """Возвращает разницу в секундах между текущим моментом и датой."""
        target_dt = DateToolkit.parse(date_string)
        if not target_dt:
            return None
        
        now = datetime.now(timezone.utc)
        return int((target_dt - now).total_seconds())

# --- Демонстрация работы ---

if __name__ == "__main__":
    toolkit = DateToolkit()

    # Список тестовых форматов
    test_dates = [
        "2026-01-17",
        "10 May 2025",
        "вчера в 15:00",
        "next Friday",
        "некорректная дата"
    ]

    print(f"{'Ввод':<25} | {'ISO Формат':<30} | {'Валидность'}")
    print("-" * 75)

    for ds in test_dates:
        valid = toolkit.is_valid(ds)
        iso = toolkit.format_to_iso(ds) if valid else "N/A"
        print(f"{ds:<25} | {iso:<30} | {valid}")

    # Пример относительного времени
    diff = toolkit.get_relative_diff("in 2 hours")
    print(f"\nСекунд до 'in 2 hours': {diff}")