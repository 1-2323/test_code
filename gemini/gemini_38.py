import csv
import json
import io
from typing import List, Dict, Any, Union
from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator
from fastapi import FastAPI, UploadFile, File, HTTPException

# --- 1. Схема данных (Валидатор) ---

class UserImportSchema(BaseModel):
    """
    Строгая схема данных для импорта пользователей.
    Автоматически проверяет типы и форматы.
    """
    external_id: int = Field(..., gt=0)
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    age: int = Field(..., ge=18, le=120)
    role: str = "user"

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {'admin', 'user', 'manager'}
        if v.lower() not in allowed:
            raise ValueError(f"Недопустимая роль. Разрешены: {allowed}")
        return v.lower()

# --- 2. Сервис импорта ---

class DataImporter:
    """
    Класс-загрузчик, отвечающий за парсинг различных форматов
    и запуск процесса валидации.
    """

    def __init__(self, schema_class: type[BaseModel]):
        self.schema = schema_class

    def process_json(self, data: bytes) -> List[Dict[str, Any]]:
        """Парсинг JSON данных."""
        try:
            items = json.loads(data)
            if not isinstance(items, list):
                items = [items]
            return self._validate_batch(items)
        except json.JSONDecodeError:
            raise ValueError("Некорректный формат JSON")

    def process_csv(self, data: bytes) -> List[Dict[str, Any]]:
        """Парсинг CSV данных."""
        stream = io.StringIO(data.decode("utf-8"))
        reader = csv.DictReader(stream)
        return self._validate_batch(list(reader))

    def _validate_batch(self, items: List[Dict]) -> List[Dict[str, Any]]:
        """Проверка каждой строки на соответствие схеме."""
        validated_data = []
        errors = []

        for index, item in enumerate(items):
            try:
                # Создание объекта Pydantic выполняет всю валидацию
                valid_item = self.schema(**item)
                validated_data.append(valid_item.model_dump())
            except ValidationError as e:
                errors.append({
                    "row": index + 1,
                    "error": e.errors(include_url=False, include_context=False)
                })

        if errors:
            # Если есть ошибки, прерываем импорт и возвращаем подробности
            raise HTTPException(status_code=422, detail={"validation_errors": errors})
        
        return validated_data

# --- 3. API Эндпоинт ---

app = FastAPI()
importer = DataImporter(UserImportSchema)

@app.post("/import")
async def import_data(file: UploadFile = File(...)):
    """
    Эндпоинт для загрузки файлов. Поддерживает .csv и .json.
    """
    content = await file.read()
    
    try:
        if file.filename.endswith(".json"):
            results = importer.process_json(content)
        elif file.filename.endswith(".csv"):
            results = importer.process_csv(content)
        else:
            return {"error": "Поддерживаются только .csv и .json файлы"}

        # Здесь логика сохранения в БД (results — это список проверенных словарей)
        # db.users.insert_many(results)
        
        return {
            "status": "success",
            "imported_count": len(results),
            "preview": results[:2]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    print("Сервис импорта запущен. Ожидание файлов для валидации...")