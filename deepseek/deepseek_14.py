from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from bson import json_util
import json

# Модель для фильтров
class FilterCondition(BaseModel):
    field: str
    operator: str  # eq, ne, gt, lt, in, nin, regex
    value: Any

class ComplexFilter(BaseModel):
    conditions: List[FilterCondition]
    logical_operator: str = "AND"  # AND или OR

class SearchRequest(BaseModel):
    filters: ComplexFilter
    projection: Optional[Dict[str, int]] = None
    sort: Optional[Dict[str, int]] = None
    limit: int = 100
    skip: int = 0

class MongoDBService:
    """
    Сервис для работы с MongoDB с использованием Motor (асинхронный драйвер).
    """
    
    def __init__(self, connection_string: str, database_name: str):
        """
        Инициализация подключения к MongoDB.
        
        Args:
            connection_string: Строка подключения к MongoDB
            database_name: Название базы данных
        """
        self.client = AsyncIOMotorClient(connection_string)
        self.db = self.client[database_name]
    
    def _build_mongo_query(self, filters: ComplexFilter) -> Dict[str, Any]:
        """
        Преобразует сложные фильтры в запрос MongoDB.
        
        Args:
            filters: Объект ComplexFilter с условиями
            
        Returns:
            Словарь для использования в find()
        """
        mongo_conditions = []
        
        for condition in filters.conditions:
            field = condition.field
            operator = condition.operator
            value = condition.value
            
            # Маппинг операторов на операторы MongoDB
            operator_map = {
                "eq": "$eq",
                "ne": "$ne",
                "gt": "$gt",
                "gte": "$gte",
                "lt": "$lt",
                "lte": "$lte",
                "in": "$in",
                "nin": "$nin",
                "regex": "$regex"
            }
            
            if operator in operator_map:
                mongo_operator = operator_map[operator]
                mongo_conditions.append({field: {mongo_operator: value}})
            else:
                raise ValueError(f"Unsupported operator: {operator}")
        
        # Объединение условий по логическому оператору
        if filters.logical_operator.upper() == "AND":
            return {"$and": mongo_conditions} if len(mongo_conditions) > 1 else mongo_conditions[0]
        elif filters.logical_operator.upper() == "OR":
            return {"$or": mongo_conditions} if len(mongo_conditions) > 1 else mongo_conditions[0]
        else:
            raise ValueError("Logical operator must be AND or OR")
    
    async def search_documents(
        self,
        collection_name: str,
        request: SearchRequest
    ) -> List[Dict[str, Any]]:
        """
        Выполняет поиск документов по сложным фильтрам.
        
        Args:
            collection_name: Имя коллекции для поиска
            request: Объект SearchRequest с параметрами поиска
            
        Returns:
            Список найденных документов
        """
        collection = self.db[collection_name]
        
        # Построение запроса
        query = self._build_mongo_query(request.filters)
        
        # Построение курсора с учетом всех параметров
        cursor = collection.find(
            query,
            projection=request.projection
        ).skip(request.skip).limit(request.limit)
        
        if request.sort:
            cursor = cursor.sort(list(request.sort.items()))
        
        # Получение результатов
        results = await cursor.to_list(length=request.limit)
        
        # Конвертация ObjectId в строку для JSON сериализации
        return json.loads(json_util.dumps(results))

# Пример использования
async def example_usage():
    service = MongoDBService(
        connection_string="mongodb://localhost:27017",
        database_name="my_database"
    )
    
    request = SearchRequest(
        filters=ComplexFilter(
            conditions=[
                FilterCondition(field="status", operator="eq", value="active"),
                FilterCondition(field="age", operator="gte", value=18),
                FilterCondition(field="tags", operator="in", value=["python", "mongodb"])
            ],
            logical_operator="AND"
        ),
        projection={"name": 1, "email": 1, "_id": 0},
        sort={"created_at": -1},
        limit=50
    )
    
    results = await service.search_documents("users", request)
    return results