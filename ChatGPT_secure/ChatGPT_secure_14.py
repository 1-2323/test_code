from typing import Any, Dict, List, Union, Optional

from pydantic import BaseModel, Field, ConfigDict, ValidationError
from pymongo import MongoClient
from pymongo.collection import Collection


# =========================
# ИСКЛЮЧЕНИЯ
# =========================

class DocumentSearchError(Exception):
    pass


class InvalidQueryOperatorError(DocumentSearchError):
    pass


# =========================
# Pydantic СХЕМЫ ФИЛЬТРОВ
# =========================

class RangeFilter(BaseModel):
    """
    Диапазонный фильтр для числовых/датовых полей.
    """
    gte: Optional[Union[int, float]] = None
    lte: Optional[Union[int, float]] = None

    model_config = ConfigDict(extra="forbid")


class FieldFilter(BaseModel):
    """
    Фильтр для одного поля.
    """
    eq: Optional[Union[str, int, float, bool]] = None
    in_list: Optional[List[Union[str, int, float]]] = Field(
        default=None,
        alias="in",
    )
    range: Optional[RangeFilter] = None

    model_config = ConfigDict(extra="forbid")


class DocumentSearchQuery(BaseModel):
    """
    Корневой объект поискового запроса.
    """
    filters: Dict[str, FieldFilter]
    limit: int = Field(default=20, ge=1, le=100)

    model_config = ConfigDict(extra="forbid")


# =========================
# СЕРВИС ПОИСКА
# =========================

class MongoDocumentSearchService:
    """
    Сервис безопасного поиска документов в MongoDB.
    """

    ALLOWED_OPERATORS = {"$eq", "$in", "$gte", "$lte"}

    def __init__(self, collection: Collection) -> None:
        self._collection: Collection = collection

    def search(self, raw_query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Выполняет поиск документов по валидированному запросу.
        """
        query_model = self._validate_query(raw_query)
        mongo_filter = self._build_mongo_filter(query_model.filters)

        cursor = self._collection.find(
            filter=mongo_filter,
            limit=query_model.limit,
        )

        return list(cursor)

    def _validate_query(self, raw_query: Dict[str, Any]) -> DocumentSearchQuery:
        """
        Проверяет входящий JSON на соответствие строгой схеме.
        """
        try:
            return DocumentSearchQuery.model_validate(raw_query)
        except ValidationError as exc:
            raise DocumentSearchError("Некорректная структура поискового запроса") from exc

    def _build_mongo_filter(
        self,
        filters: Dict[str, FieldFilter],
    ) -> Dict[str, Any]:
        """
        Преобразует фильтры в MongoDB-запрос,
        разрешая только допустимые операторы.
        """
        mongo_filter: Dict[str, Any] = {}

        for field_name, field_filter in filters.items():
            field_query: Dict[str, Any] = {}

            if field_filter.eq is not None:
                field_query["$eq"] = field_filter.eq

            if field_filter.in_list is not None:
                field_query["$in"] = field_filter.in_list

            if field_filter.range is not None:
                if field_filter.range.gte is not None:
                    field_query["$gte"] = field_filter.range.gte
                if field_filter.range.lte is not None:
                    field_query["$lte"] = field_filter.range.lte

            self._assert_allowed_operators(field_query)
            mongo_filter[field_name] = field_query

        return mongo_filter

    def _assert_allowed_operators(self, field_query: Dict[str, Any]) -> None:
        """
        Блокирует любые MongoDB-операторы,
        не разрешённые логикой приложения.
        """
        for operator in field_query.keys():
            if operator not in self.ALLOWED_OPERATORS:
                raise InvalidQueryOperatorError(
                    f"Оператор {operator} запрещён"
                )


# =========================
# ИНИЦИАЛИЗАЦИЯ MONGODB
# =========================

client = MongoClient("mongodb://localhost:27017")
database = client["example_db"]
collection = database["documents"]

document_search_service = MongoDocumentSearchService(collection)
