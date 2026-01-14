from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, date
from bson import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
import re

router = APIRouter()

# Pydantic модели для запроса и ответа
class DateRange(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None

class SearchCriteria(BaseModel):
    text: Optional[str] = Field(None, description="Полнотекстовый поиск")
    title: Optional[str] = Field(None, description="Поиск по заголовку")
    category: Optional[Union[str, List[str]]] = Field(None, description="Категория или список категорий")
    tags: Optional[List[str]] = Field(None, description="Список тегов")
    author: Optional[str] = Field(None, description="Автор документа")
    status: Optional[str] = Field(None, description="Статус документа")
    created_at: Optional[DateRange] = Field(None, description="Диапазон дат создания")
    updated_at: Optional[DateRange] = Field(None, description="Диапазон дат обновления")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Дополнительные метаданные")
    min_views: Optional[int] = Field(None, ge=0, description="Минимальное количество просмотров")
    max_views: Optional[int] = Field(None, ge=0, description="Максимальное количество просмотров")
    is_published: Optional[bool] = Field(None, description="Опубликован ли документ")

    @field_validator('category')
    @classmethod
    def validate_category(cls, v):
        if isinstance(v, str):
            return [v]
        return v

class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, description="Номер страницы")
    limit: int = Field(20, ge=1, le=100, description="Количество элементов на странице")
    sort_by: Optional[str] = Field("created_at", description="Поле для сортировки")
    sort_order: Optional[str] = Field("desc", pattern="^(asc|desc)$", description="Порядок сортировки")

class DocumentResponse(BaseModel):
    id: str
    title: str
    content: str
    category: List[str]
    tags: List[str]
    author: str
    status: str
    views: int
    is_published: bool
    created_at: datetime
    updated_at: datetime
    metadata: Optional[Dict[str, Any]] = None

class SearchResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool

# Подключение к MongoDB
def get_mongo_collection() -> Collection:
    client = MongoClient("mongodb://localhost:27017/")
    db = client["documents_db"]
    return db["documents"]

@router.get("/documents/search", response_model=SearchResponse)
async def search_documents(
    criteria: SearchCriteria = Depends(),
    pagination: PaginationParams = Depends()
):
    """
    Поиск документов в MongoDB по заданным критериям
    """
    try:
        collection = get_mongo_collection()
        
        # Строим запрос для MongoDB
        query = build_mongo_query(criteria)
        
        # Получаем общее количество документов
        total = collection.count_documents(query)
        
        # Определяем сортировку
        sort_order = DESCENDING if pagination.sort_order == "desc" else ASCENDING
        sort_field = pagination.sort_by if pagination.sort_by in [
            "created_at", "updated_at", "views", "title"
        ] else "created_at"
        
        # Выполняем поиск с пагинацией
        skip = (pagination.page - 1) * pagination.limit
        documents_cursor = collection.find(query).skip(skip).limit(pagination.limit).sort(sort_field, sort_order)
        
        # Преобразуем документы в Pydantic модель
        documents = []
        for doc in documents_cursor:
            # Конвертируем ObjectId в строку
            doc["id"] = str(doc.pop("_id"))
            
            # Обеспечиваем наличие всех полей
            doc.setdefault("category", [])
            doc.setdefault("tags", [])
            doc.setdefault("metadata", {})
            
            documents.append(DocumentResponse(**doc))
        
        # Рассчитываем пагинацию
        total_pages = (total + pagination.limit - 1) // pagination.limit if total > 0 else 0
        
        return SearchResponse(
            documents=documents,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=total_pages,
            has_next=pagination.page < total_pages,
            has_prev=pagination.page > 1
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при поиске документов: {str(e)}"
        )

def build_mongo_query(criteria: SearchCriteria) -> Dict[str, Any]:
    """Построение MongoDB запроса из критериев поиска"""
    query = {}
    
    # Текстовый поиск (использует MongoDB text index)
    if criteria.text:
        query["$text"] = {"$search": criteria.text}
    
    # Поиск по заголовку (регистронезависимый)
    if criteria.title:
        query["title"] = {"$regex": re.escape(criteria.title), "$options": "i"}
    
    # Фильтр по категории
    if criteria.category:
        if len(criteria.category) == 1:
            query["category"] = criteria.category[0]
        else:
            query["category"] = {"$in": criteria.category}
    
    # Фильтр по тегам
    if criteria.tags:
        query["tags"] = {"$all": criteria.tags}
    
    # Фильтр по автору
    if criteria.author:
        query["author"] = criteria.author
    
    # Фильтр по статусу
    if criteria.status:
        query["status"] = criteria.status
    
    # Диапазон дат создания
    if criteria.created_at:
        date_query = {}
        if criteria.created_at.start:
            date_query["$gte"] = datetime.combine(criteria.created_at.start, datetime.min.time())
        if criteria.created_at.end:
            date_query["$lte"] = datetime.combine(criteria.created_at.end, datetime.max.time())
        if date_query:
            query["created_at"] = date_query
    
    # Диапазон дат обновления
    if criteria.updated_at:
        date_query = {}
        if criteria.updated_at.start:
            date_query["$gte"] = datetime.combine(criteria.updated_at.start, datetime.min.time())
        if criteria.updated_at.end:
            date_query["$lte"] = datetime.combine(criteria.updated_at.end, datetime.max.time())
        if date_query:
            query["updated_at"] = date_query
    
    # Фильтр по количеству просмотров
    views_query = {}
    if criteria.min_views is not None:
        views_query["$gte"] = criteria.min_views
    if criteria.max_views is not None:
        views_query["$lte"] = criteria.max_views
    if views_query:
        query["views"] = views_query
    
    # Фильтр по статусу публикации
    if criteria.is_published is not None:
        query["is_published"] = criteria.is_published
    
    # Фильтр по метаданным
    if criteria.metadata:
        for key, value in criteria.metadata.items():
            query[f"metadata.{key}"] = value
    
    return query

# Эндпоинт для получения списка доступных категорий
@router.get("/documents/categories")
async def get_categories():
    """Получение списка уникальных категорий"""
    try:
        collection = get_mongo_collection()
        categories = collection.distinct("category")
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при получении категорий: {str(e)}"
        )

# Эндпоинт для получения списка популярных тегов
@router.get("/documents/tags")
async def get_tags(limit: int = Query(20, ge=1, le=100)):
    """Получение списка популярных тегов"""
    try:
        collection = get_mongo_collection()
        
        # Агрегация для получения наиболее часто используемых тегов
        pipeline = [
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit}
        ]
        
        result = list(collection.aggregate(pipeline))
        tags = [{"tag": item["_id"], "count": item["count"]} for item in result]
        
        return {"tags": tags}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при получении тегов: {str(e)}"
        )