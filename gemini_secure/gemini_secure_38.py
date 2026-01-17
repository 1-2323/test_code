import csv
import json
import io
from typing import List, Dict, Any, Union, Final
from pydantic import BaseModel, Field, ValidationError, ConfigDict


# --- Схема валидации данных ---

class ImportSchema(BaseModel):
    """
    Строгая схема данных для импорта.
    Определяет типы, ограничения и обязательные поля.
    """
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    external_id: int = Field(..., gt=0)
    product_name: str = Field(..., min_length=2, max_length=100)
    price: float = Field(..., ge=0.0)
    category: str = Field(..., pattern=r"^(electronics|clothing|home)$")
    is_active: bool = True


# --- Сервис импорта ---

class DataImportService:
    """
    Сервис для импорта и валидации данных из внешних файлов.
    Поддерживает форматы JSON и CSV.
    """

    MAX_ROWS: Final[int] = 10000  # Защита от DoS (слишком большие файлы)

    def __init__(self):
        self.validated_data: List[ImportSchema] = []

    def _validate_batch(self, rows: List[Dict[str, Any]]):
        """
        Проверяет массив данных на соответствие схеме. 
        При любой ошибке выбрасывает исключение.
        """
        if len(rows) > self.MAX_ROWS:
            raise ValueError(f"File too large. Maximum {self.MAX_ROWS} rows allowed.")
        
        temporary_buffer = []
        for index, row in enumerate(rows):
            try:
                # Валидация строки
                valid_row = ImportSchema(**row)
                temporary_buffer.append(valid_row)
            except ValidationError as e:
                # Отклоняем весь файл, указывая на ошибку в конкретной строке
                raise ValueError(f"Validation error at row {index + 1}: {e.errors()}")
        
        self.validated_data = temporary_buffer

    def import_json(self, raw_content: str):
        """Парсинг и валидация JSON контента."""
        try:
            data = json.loads(raw_content)
            if not isinstance(data, list):
                raise ValueError("JSON must be an array of objects.")
            self._validate_batch(data)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format.")

    def import_csv(self, raw_content: str):
        """Парсинг и валидация CSV контента."""
        stream = io.StringIO(raw_content)
        reader = csv.DictReader(stream)
        
        # Проверяем наличие заголовков
        if not reader.fieldnames:
            raise ValueError("CSV file is empty or missing headers.")

        # Преобразуем итератор в список для пакетной валидации
        rows = list(reader)
        self._validate_batch(rows)

    def save_to_db(self):
        """Имитация сохранения валидированных данных в БД."""
        if not self.validated_data:
            raise ValueError("No validated data to save.")
        
        print(f"Successfully imported {len(self.validated_data)} records.")
        # Logic: db.session.add_all(self.validated_data) -> db.session.commit()
        return True


# --- Пример использования ---

# csv_content = "external_id,product_name,price,category,is_active\n101,Laptop,999.99,electronics,true"
# importer = DataImportService()
# try:
#     importer.import_csv(csv_content)
#     importer.save_to_db()
# except ValueError as err:
#     print(f"Import failed: {err}")