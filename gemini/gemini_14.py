import asyncio
from typing import Dict, Any, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

class DocumentSearchService:
    """
    Сервис для выполнения сложных поисковых запросов в MongoDB.
    Использует асинхронный драйвер motor.
    """

    def __init__(self, db_url: str, db_name: str, collection_name: str):
        """Инициализация подключения к коллекции."""
        self.client = AsyncIOMotorClient(db_url)
        self.db = self.client[db_name]
        self.collection: AsyncIOMotorCollection = self.db[collection_name]

    def _build_mongo_query(self, client_filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Преобразует JSON-фильтры клиента в синтаксис MongoDB Query API.
        Поддерживает: 
        - Точное совпадение
        - Диапазоны (min/max)
        - Списки значений (in)
        """
        mongo_query = {}

        for key, value in client_filters.items():
            if isinstance(value, dict):
                # Обработка диапазонов: {"price": {"min": 100, "max": 500}}
                field_query = {}
                if "min" in value:
                    field_query["$gte"] = value["min"]
                if "max" in value:
                    field_query["$lte"] = value["max"]
                if field_query:
                    mongo_query[key] = field_query
            
            elif isinstance(value, list):
                # Обработка списков: {"tags": ["work", "urgent"]} -> { "tags": { "$in": [...] } }
                mongo_query[key] = {"$in": value}
            
            else:
                # Точное совпадение
                mongo_query[key] = value

        return mongo_query

    async def find_documents(
        self, 
        filters: Dict[str, Any], 
        limit: int = 10, 
        skip: int = 0,
        sort_by: str = "_id",
        descending: bool = True
    ) -> Dict[str, Any]:
        """
        Выполняет поиск документов с пагинацией и сортировкой.
        
        :param filters: Сложный JSON объект с критериями.
        :param limit: Количество документов на странице.
        :param skip: Смещение для пагинации.
        :return: Словарь с результатами и метаданными.
        """
        # 1. Формируем запрос
        query = self._build_mongo_query(filters)
        
        # 2. Определяем направление сортировки
        sort_direction = -1 if descending else 1

        # 3. Выполняем асинхронный запрос и подсчет общего количества
        cursor = self.collection.find(query).sort(sort_by, sort_direction).skip(skip).limit(limit)
        
        documents = await cursor.to_list(length=limit)
        total_count = await self.collection.count_documents(query)

        # 4. Формируем ответ
        return {
            "data": documents,
            "pagination": {
                "total": total_count,
                "limit": limit,
                "skip": skip,
                "has_more": total_count > (skip + limit)
            }
        }

# --- Демонстрация работы (асинхронно) ---

async def main():
    # Настройки подключения
    MONGO_URI = "mongodb://localhost:27017"
    service = DocumentSearchService(MONGO_URI, "app_db", "documents")

    # Пример сложного JSON-фильтра от клиента
    client_payload = {
        "status": "active",
        "category": ["electronics", "gadgets"],
        "price": {"min": 100, "max": 1000},
        "brand": "Apple"
    }

    try:
        print("Выполнение поиска документов...")
        results = await service.find_documents(
            filters=client_payload,
            limit=5,
            skip=0
        )
        
        print(f"Найдено документов: {results['pagination']['total']}")
        for doc in results['data']:
            print(f"ID: {doc.get('_id')} | Title: {doc.get('title', 'N/A')}")
            
    except Exception as e:
        print(f"Ошибка при поиске: {e}")

if __name__ == "__main__":
    # Запуск асинхронного примера
    # asyncio.run(main()) # Раскомментировать при наличии запущенной MongoDB
    pass