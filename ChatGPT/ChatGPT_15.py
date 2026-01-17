from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.cursor import Cursor
from pydantic import BaseModel, Field


# =========================
# Pydantic-модели фильтров
# =========================

class Pagination(BaseModel):
    """
    Модель пагинации.
    """
    limit: int = Field(10, ge=1, le=100)
    offset: int = Field(0, ge=0)


class SortOption(BaseModel):
    """
    Модель сортировки.
    """
    field: str
    direction: int = Field(..., description="1 for ASC, -1 for DESC")


class SearchFilters(BaseModel):
    """
    Модель сложных фильтров поиска.
    """
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description="MongoDB-совместимые фильтры",
    )
    sort: Optional[SortOption] = None
    pagination: Pagination = Pagination()


# =========================
# Сервис поиска документов
# =========================

class MongoDocumentSearchService:
    """
    Сервис для поиска документов в MongoDB.
    """

    def __init__(
        self,
        mongo_uri: str,
        database_name: str,
        collection_name: str,
    ) -> None:
        self._client: MongoClient = MongoClient(mongo_uri)
        self._collection: Collection = (
            self._client[database_name][collection_name]
        )

    def search(self, search_filters: SearchFilters) -> Dict[str, Any]:
        """
        Выполняет поиск документов по сложным фильтрам.

        Алгоритм:
        1. Формирование MongoDB-запроса
        2. Применение сортировки (если указана)
        3. Применение limit / offset
        4. Подсчёт общего количества документов
        """
        query: Dict[str, Any] = self._build_query(search_filters.filters)

        cursor: Cursor = self._collection.find(query)

        total: int = self._collection.count_documents(query)

        if search_filters.sort:
            cursor = cursor.sort(
                search_filters.sort.field,
                search_filters.sort.direction,
            )

        cursor = cursor.skip(search_filters.pagination.offset)
        cursor = cursor.limit(search_filters.pagination.limit)

        documents: List[Dict[str, Any]] = list(cursor)

        return {
            "total": total,
            "limit": search_filters.pagination.limit,
            "offset": search_filters.pagination.offset,
            "items": documents,
        }

    # =========================
    # Внутренние методы
    # =========================

    @staticmethod
    def _build_query(raw_filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Формирует MongoDB-запрос из JSON-фильтров клиента.

        Пример входного JSON:
        {
            "status": "active",
            "age": {"$gte": 18},
            "$or": [
                {"role": "admin"},
                {"role": "moderator"}
            ]
        }
        """
        if not isinstance(raw_filters, dict):
            raise ValueError("Filters must be a JSON object")

        return raw_filters


# =========================
# Пример использования
# =========================

def example_usage() -> None:
    """
    Демонстрация работы сервиса поиска.
    """
    service = MongoDocumentSearchService(
        mongo_uri="mongodb://localhost:27017",
        database_name="app_db",
        collection_name="documents",
    )

    search_request = SearchFilters(
        filters={
            "status": "active",
            "price": {"$gte": 100},
            "$or": [
                {"category": "books"},
                {"category": "electronics"},
            ],
        },
        sort=SortOption(field="created_at", direction=-1),
        pagination=Pagination(limit=5, offset=0),
    )

    result = service.search(search_request)
    print(result)
