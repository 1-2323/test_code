import csv
import json
from pathlib import Path
from typing import Any, Iterable, List, Protocol

from pydantic import BaseModel, EmailStr, ValidationError, field_validator


# ==================================================
# Исключения
# ==================================================

class ImportErrorBase(Exception):
    """Базовая ошибка импорта."""


class SchemaValidationError(ImportErrorBase):
    """Ошибка валидации схемы данных."""


class UnsupportedFileFormatError(ImportErrorBase):
    """Неподдерживаемый формат файла."""


# ==================================================
# Схема данных (строгая)
# ==================================================

class ImportSchema(BaseModel):
    """
    Строгая схема импортируемых данных.
    """
    user_id: int
    name: str
    email: EmailStr
    balance: float
    is_active: bool

    @field_validator("balance")
    @classmethod
    def balance_must_be_positive(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Balance must be non-negative")
        return value


# ==================================================
# Контракт репозитория
# ==================================================

class Repository(Protocol):
    """
    Контракт слоя сохранения данных.
    """

    def save(self, model: ImportSchema) -> None:
        ...


# ==================================================
# Валидатор строки
# ==================================================

class RowValidator:
    """
    Проверяет одну строку входных данных.
    """

    def validate(self, raw_row: dict[str, Any]) -> ImportSchema:
        try:
            return ImportSchema(**raw_row)
        except ValidationError as exc:
            raise SchemaValidationError(str(exc)) from exc


# ==================================================
# Импортёр данных
# ==================================================

class DataImporter:
    """
    Сервис импорта данных из CSV или JSON.
    """

    def __init__(
        self,
        repository: Repository,
        validator: RowValidator,
    ) -> None:
        self._repository = repository
        self._validator = validator

    # =========================
    # Public API
    # =========================

    def import_file(self, file_path: Path) -> int:
        """
        Импортирует файл и возвращает количество сохранённых записей.
        """
        rows = self._load_rows(file_path)

        imported_count = 0
        for row in rows:
            model = self._validator.validate(row)
            self._repository.save(model)
            imported_count += 1

        return imported_count

    # =========================
    # Внутренняя логика
    # =========================

    def _load_rows(self, file_path: Path) -> Iterable[dict[str, Any]]:
        if file_path.suffix == ".csv":
            return self._load_csv(file_path)
        if file_path.suffix == ".json":
            return self._load_json(file_path)

        raise UnsupportedFileFormatError(
            f"Unsupported file type: {file_path.suffix}"
        )

    @staticmethod
    def _load_csv(file_path: Path) -> List[dict[str, Any]]:
        with open(file_path, newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            return [dict(row) for row in reader]

    @staticmethod
    def _load_json(file_path: Path) -> List[dict[str, Any]]:
        with open(file_path, encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise ImportErrorBase("JSON file must contain a list of objects")

        return data


# ==================================================
# Пример репозитория (БД)
# ==================================================

class InMemoryRepository:
    """
    Пример репозитория.
    В проде заменяется на SQLAlchemy.
    """

    def __init__(self) -> None:
        self._storage: list[ImportSchema] = []

    def save(self, model: ImportSchema) -> None:
        self._storage.append(model)
