import asyncio
from typing import List, Optional, Dict, Any, Final
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, field_validator, ConfigDict


# --- Схемы валидации (Защита от NoSQL Injection) ---

class DateRangeFilter(BaseModel):
    """Разрешенный формат для фильтрации по датам."""
    model_config = ConfigDict(extra='forbid')
    
    gte: Optional[str] = Field(None, alias="$gte")
    lte: Optional[str] = Field(None, alias="$lte")


class DocumentSearchSchema(BaseModel):
    """
    Строгая схема входящего запроса. 
    Атрибут extra='forbid' блокирует любые недокументированные поля и операторы.
    """
    model_config = ConfigDict(extra='forbid')

    # Разрешаем поиск только по конкретным полям
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    category: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_-]+$")
    author_id: Optional[int] = None
    created_at: Optional[DateRangeFilter] = None

    @field_validator("*", mode="before")
    @classmethod
    def block_operators(cls, v: Any) -> Any:
        """
        Проверяет, чтобы значения не содержали объектов с ключами-операторами,
        если это не предусмотрено схемой (как в DateRangeFilter).
        """
        if isinstance(v, dict):
            # Проверяем ключи на наличие символа '$'
            for key in v.keys():
                if str(key).startswith("$") and key not in ["$gte", "$lte"]:
                    raise ValueError(f"Forbidden MongoDB operator detected: {key}")
        return v


# --- Сервис поиска документов ---

class MongoDocumentService:
    """
    Сервис для работы с MongoDB, обеспечивающий безопасную фильтрацию.
    """

    def __init__(self, connection_uri: str, db_name: str):
        self._client = AsyncIOMotorClient(connection_uri)
        self._db = self._client[db_name]
        self._collection = self._db["documents"]

    async def search_documents(self, raw_filters: Dict[str, Any], limit: int = 50) -> List[Dict[str, Any]]:
        """
        Выполняет валидацию и поиск в БД.
        
        :param raw_filters: Необработанный JSON от клиента.
        :param limit: Максимальное количество документов.
        :return: Список найденных документов.
        """
        # 1. Валидация через Pydantic (отсеивание $ операторов и лишних полей)
        try:
            validated_criteria = DocumentSearchSchema(**raw_filters)
        except Exception as e:
            raise ValueError(f"Invalid search criteria: {str(e)}")

        # 2. Формирование запроса (используем только проверенные данные)
        # model_dump(exclude_none=True, by_alias=True) преобразует gte обратно в $gte для Mongo
        query = validated_criteria.model_dump(exclude_none=True, by_alias=True)

        # 3. Выполнение асинхронного запроса
        cursor = self._collection.find(query).limit(limit)
        
        results = []
        async for doc in cursor:
            # Преобразуем ObjectId в строку для JSON-совместимости
            doc["_id"] = str(doc["_id"])
            results.append(doc)
            
        return results

# --- Пример инициализации и запуска ---

async def main():
    # Имитация входящих данных (попытка инъекции через $ne будет заблокирована Pydantic)
    malicious_input = {
        "category": "legal",
        "author_id": {"$ne": 0},  # Это вызовет ошибку валидации
        "title": "Contract"
    }

    service = MongoDocumentService("mongodb://localhost:27017", "app_db")
    
    try:
        docs = await service.search_documents(malicious_input)
        print(f"Found {len(docs)} documents")
    except ValueError as e:
        print(f"Security Alert: {e}")

if __name__ == "__main__":
    # asyncio.run(main()) # Раскомментировать для запуска
    pass