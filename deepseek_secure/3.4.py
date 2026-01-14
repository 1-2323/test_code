from fastapi import FastAPI, HTTPException, Depends, Query, Request
from pymongo import MongoClient, ASCENDING
from pymongo.errors import PyMongoError
from bson import ObjectId, regex
from bson.errors import InvalidId
from typing import Optional, Dict, Any, List
import re
from datetime import datetime

app = FastAPI(title="Document Search API")

# Конфигурация MongoDB (в реальном приложении вынесите в настройки)
MONGODB_URL = "mongodb://localhost:27017"
DATABASE_NAME = "documents_db"
COLLECTION_NAME = "documents"

def get_mongo_client():
    """Зависимость для получения MongoDB клиента"""
    client = MongoClient(MONGODB_URL)
    try:
        yield client
    finally:
        client.close()

def sanitize_value(value: Any) -> Any:
    """Санитизация значений для предотвращения NoSQL-инъекций"""
    if isinstance(value, dict):
        return sanitize_dict(value)
    elif isinstance(value, list):
        return [sanitize_value(item) for item in value]
    elif isinstance(value, str):
        # Проверяем, является ли строка ObjectId
        if re.match(r'^[0-9a-fA-F]{24}$', value):
            try:
                return ObjectId(value)
            except InvalidId:
                pass
        return value
    return value

def sanitize_dict(query_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Санитизация словаря запроса"""
    sanitized = {}
    allowed_operators = {
        '$eq', '$ne', '$gt', '$gte', '$lt', '$lte', '$in', '$nin',
        '$exists', '$regex', '$options', '$text', '$search',
        '$and', '$or', '$not', '$nor', '$all', '$elemMatch',
        '$size', '$type'
    }
    
    for key, value in query_dict.items():
        # Если ключ начинается с $, проверяем что это разрешенный оператор
        if key.startswith('$'):
            if key not in allowed_operators:
                raise HTTPException(
                    status_code=400,
                    detail=f"Недопустимый оператор: {key}"
                )
            
            # Особые проверки для определенных операторов
            if key == '$regex':
                if not isinstance(value, str):
                    raise HTTPException(
                        status_code=400,
                        detail="$regex требует строковое значение"
                    )
                # Экранируем специальные символы в регулярных выражениях
                value = re.escape(value)
            
            elif key in ['$gt', '$gte', '$lt', '$lte', '$ne']:
                # Для операторов сравнения проверяем типы
                if not isinstance(value, (int, float, datetime, str)):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Оператор {key} требует числовое значение, дату или строку"
                    )
            
            elif key in ['$in', '$nin', '$all']:
                if not isinstance(value, list):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Оператор {key} требует массив значений"
                    )
                value = [sanitize_value(item) for item in value]
            
            elif key == '$and' or key == '$or' or key == '$nor':
                if not isinstance(value, list):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Оператор {key} требует массив условий"
                    )
                value = [sanitize_dict(item) for item in value]
        
        # Рекурсивная санитизация вложенных словарей
        if isinstance(value, dict):
            value = sanitize_dict(value)
        elif isinstance(value, list):
            value = [sanitize_value(item) for item in value]
        else:
            value = sanitize_value(value)
        
        sanitized[key] = value
    
    return sanitized

def build_search_query(criteria: Dict[str, Any]) -> Dict[str, Any]:
    """Построение безопасного поискового запроса"""
    query = {}
    
    for field, condition in criteria.items():
        # Пропускаем служебные поля
        if field.startswith('$'):
            continue
            
        if isinstance(condition, dict):
            # Если условие - словарь, санитизируем его
            query[field] = sanitize_dict(condition)
        else:
            # Простое сравнение на равенство
            query[field] = sanitize_value(condition)
    
    return query

class SearchCriteria(BaseModel):
    """Модель критериев поиска"""
    criteria: Dict[str, Any] = Field(
        default_factory=dict,
        description="Критерии поиска в формате MongoDB query"
    )
    projection: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Поля для включения/исключения в результатах"
    )
    sort: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Поля для сортировки (1 - по возрастанию, -1 - по убыванию)"
    )
    skip: Optional[int] = Field(
        default=0,
        ge=0,
        description="Количество документов для пропуска"
    )
    limit: Optional[int] = Field(
        default=100,
        ge=1,
        le=1000,
        description="Максимальное количество документов в результате"
    )

@app.get("/documents/search", response_model=List[Dict[str, Any]])
async def search_documents(
    search_criteria: SearchCriteria,
    request: Request,
    mongo_client: MongoClient = Depends(get_mongo_client)
):
    """
    Поиск документов по критериям
    
    - **criteria**: Словарь с критериями поиска в формате MongoDB query
    - **projection**: Опциональные поля для выборки
    - **sort**: Опциональная сортировка результатов
    - **skip**: Пропустить первые N результатов
    - **limit**: Ограничить количество результатов
    """
    try:
        db = mongo_client[DATABASE_NAME]
        collection = db[COLLECTION_NAME]
        
        # Санитизация критериев поиска
        safe_criteria = build_search_query(search_criteria.criteria)
        
        # Санитизация проекции
        safe_projection = None
        if search_criteria.projection:
            safe_projection = sanitize_dict(search_criteria.projection)
        
        # Санитизация сортировки
        safe_sort = None
        if search_criteria.sort:
            safe_sort = []
            for field, direction in search_criteria.sort.items():
                if direction not in [1, -1, ASCENDING]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Недопустимое направление сортировки для поля {field}: {direction}"
                    )
                safe_sort.append((field, direction))
        
        # Выполнение запроса
        cursor = collection.find(
            filter=safe_criteria,
            projection=safe_projection
        )
        
        if safe_sort:
            cursor = cursor.sort(safe_sort)
        
        if search_criteria.skip:
            cursor = cursor.skip(search_criteria.skip)
        
        if search_criteria.limit:
            cursor = cursor.limit(search_criteria.limit)
        
        # Преобразование ObjectId в строки для JSON-ответа
        results = []
        for doc in cursor:
            doc['_id'] = str(doc['_id'])
            results.append(doc)
        
        return results
        
    except HTTPException:
        raise
    except InvalidId as e:
        raise HTTPException(
            status_code=400,
            detail="Некорректный формат ID документа"
        )
    except PyMongoError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка базы данных: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

@app.on_event("startup")
async def startup_event():
    """Создание индексов при запуске приложения"""
    try:
        client = MongoClient(MONGODB_URL)
        db = client[DATABASE_NAME]
        collection = db[COLLECTION_NAME]
        
        # Создание индексов для часто используемых полей
        collection.create_index([("created_at", ASCENDING)])
        collection.create_index([("title", "text"), ("content", "text")])
        
        client.close()
    except PyMongoError:
        # Логируем ошибку, но не падаем
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)