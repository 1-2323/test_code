import csv
import json
from pathlib import Path
from typing import Any, Iterable, List, Literal

from pydantic import BaseModel, Field, ValidationError, ConfigDict
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# =========================
# DATABASE SETUP
# =========================

DATABASE_URL = "sqlite:///./import.db"

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()


class UserRecord(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    age = Column(Integer, nullable=False)
    role = Column(String, nullable=False)


Base.metadata.create_all(engine)


# =========================
# STRICT SCHEMA
# =========================

class UserImportSchema(BaseModel):
    """
    Строгая схема данных для импорта.
    """
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")
    age: int = Field(..., ge=18, le=120)
    role: Literal["user", "admin", "moderator"]


# =========================
# VALIDATOR
# =========================

class ImportValidationError(Exception):
    pass


class DataValidator:
    """
    Валидирует входные строки по строгой схеме.
    """

    def validate_rows(self, rows: Iterable[dict[str, Any]]) -> List[UserImportSchema]:
        validated: List[UserImportSchema] = []

        for index, row in enumerate(rows, start=1):
            try:
                validated.append(UserImportSchema.model_validate(row))
            except ValidationError as exc:
                raise ImportValidationError(
                    f"Ошибка в строке {index}: {exc}"
                ) from exc

        if not validated:
            raise ImportValidationError("Файл не содержит допустимых данных")

        return validated


# =========================
# PARSERS
# =========================

class FileParser:
    """
    Парсинг CSV и JSON файлов в список словарей.
    """

    def parse(self, path: Path) -> List[dict[str, Any]]:
        if path.suffix.lower() == ".csv":
            return self._parse_csv(path)
        if path.suffix.lower() == ".json":
            return self._parse_json(path)

        raise ValueError("Неподдерживаемый формат файла")

    def _parse_csv(self, path: Path) -> List[dict[str, Any]]:
        with path.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            return [dict(row) for row in reader]

    def _parse_json(self, path: Path) -> List[dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON должен содержать массив объектов")
        return data


# =========================
# IMPORT SERVICE
# =========================

class ImportService:
    """
    Импортирует данные только если весь файл валиден.
    """

    def __init__(self) -> None:
        self._parser = FileParser()
        self._validator = DataValidator()

    def import_file(self, path: Path) -> None:
        rows = self._parser.parse(path)
        validated_rows = self._validator.validate_rows(rows)

        with SessionLocal() as db:
            try:
                db.begin()

                for item in validated_rows:
                    record = UserRecord(
                        email=item.email,
                        age=item.age,
                        role=item.role,
                    )
                    db.add(record)

                db.commit()

            except Exception:
                db.rollback()
                raise


# =========================
# ENTRYPOINT
# =========================

if __name__ == "__main__":
    service = ImportService()
    service.import_file(Path("users.csv"))
