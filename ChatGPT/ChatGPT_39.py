import csv
import json
from pathlib import Path
from typing import Any, Iterable, Protocol

from pydantic import BaseModel, EmailStr, ValidationError, field_validator


# ==================================================
# Исключения
# ==================================================

class DataImportError(Exception):
    """Базовая ошибка импорта данных."""


class RowValidationError(DataImportError):
    """Ошибка валидации строки."""


class UnsupportedFileFormat(DataImportError):
    """Неподдерживаемый формат файла."""


# ==================================================
# Строгая схема данных
# ==================================================

class ImportSchema(BaseModel):
    """
    Строгая схема данных для импорта.
    """
    user_id: int
    full_name: str
    email: EmailStr
    balance: float
    is_active: bool

    @field_validator("balance")
    @classmethod
    def balance_must_be_positive(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Balance must be >= 0")
        return value


# ==================================================
# Контракт репозитория
# ==================================================

class UserRepository(Protocol):
    """
    Контракт сохранения данных в основную БД.
    """

    def save(self, model: ImportSchema) -> None:
        ...


# ==================================================
# Валидатор строки
# ==================================================

class RowValidator:
    """
    Валидирует одну строку входных данных.
    """

    def validate(self, raw_row: dict[str, Any]) -> ImportSchema:
        try:
            return ImportSchema(**raw_row)
        except ValidationError as exc:
            raise RowValidationError(str(exc)) from exc


# ==================================================
# Сервис импорта данных
# ==================================================

class DataImportService:
    """
    Сервис импорта CSV / JSON данных.
    """

    def __init__(
        self,
        repository: UserRepository,
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

        imported = 0
        for index, row in enumerate(rows, start=1):
            try:
                model = self._validator.validate(row)
                self._repository.save(model)
                imported += 1
            except RowValidationError as exc:
                raise RowValidationError(
                    f"Row {index}: {exc}"
                ) from exc

        return imported

    # =========================
    # Загрузка данных
    # =========================

    def _load_rows(self, file_path: Path) -> Iterable[dict[str, Any]]:
        if file_path.suffix.lower() == ".csv":
            return self._load_csv(file_path)

        if file_path.suffix.lower() == ".json":
            return self._load_json(file_path)

        raise UnsupportedFileFormat(
            f"Unsupported file format: {file_path.suffix}"
        )

    @staticmethod
    def _load_csv(file_path: Path) -> list[dict[str, Any]]:
        with open(file_path, encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            return [dict(row) for row in reader]

    @staticmethod
    def _load_json(file_path: Path) -> list[dict[str, Any]]:
        with open(file_path, encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise DataImportError("JSON must contain an array of objects")

        return data


# ==================================================
# Пример репозитория (заменяется на SQLAlchemy)
# ==================================================

class InMemoryUserRepository:
    """
    Пример репозитория.
    В проде используется SQLAlchemy.
    """

    def __init__(self) -> None:
        self._storage: list[ImportSchema] = []

    def save(self, model: ImportSchema) -> None:
        self._storage.append(model)
