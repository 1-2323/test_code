from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional, List
from pydantic import BaseModel

# Модели Pydantic для запроса и ответа
class UserSearchRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    created_at: str

class PaginatedUsersResponse(BaseModel):
    users: List[UserResponse]
    total: int
    page: int
    limit: int
    total_pages: int

# Эндпоинт
router = APIRouter()

@router.get("/admin/users/search", response_model=PaginatedUsersResponse)
async def search_users(
    name: Optional[str] = Query(None, description="Поиск по имени пользователя"),
    role: Optional[str] = Query(None, description="Фильтр по роли"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    limit: int = Query(20, ge=1, le=100, description="Количество записей на странице"),
    db: AsyncSession = Depends(get_db)  # Зависимость для получения сессии БД
):
    """
    Поиск пользователей с фильтрацией и пагинацией
    """
    try:
        # Базовый запрос
        query = select(User).where(User.is_active == True)
        
        # Применяем фильтр по имени (поиск по подстроке)
        if name:
            query = query.where(
                or_(
                    User.name.ilike(f"%{name}%"),
                    User.email.ilike(f"%{name}%")
                )
            )
        
        # Применяем фильтр по роли
        if role:
            query = query.where(User.role == role)
        
        # Подсчет общего количества записей
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar()
        
        # Применяем пагинацию
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit).order_by(User.created_at.desc())
        
        # Выполняем запрос для получения пользователей
        result = await db.execute(query)
        users = result.scalars().all()
        
        # Преобразуем в Pydantic модель
        user_responses = [
            UserResponse(
                id=user.id,
                name=user.name,
                email=user.email,
                role=user.role,
                created_at=user.created_at.isoformat()
            )
            for user in users
        ]
        
        # Рассчитываем общее количество страниц
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        
        return PaginatedUsersResponse(
            users=user_responses,
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при поиске пользователей: {str(e)}"
        )