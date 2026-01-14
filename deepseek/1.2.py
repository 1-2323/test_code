from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any

# Импортируем ваши модели, схемы и зависимости
from app.database import get_db
from app.models.order import Order
from app.models.user import User
from app.schemas.order import OrderResponse
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import check_order_access

router = APIRouter(tags=["orders"])

@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Получить детали заказа по ID",
    description="Возвращает полную информацию о заказе по его идентификатору"
)
async def get_order_by_id(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Получение деталей заказа по ID.
    
    Args:
        order_id: Идентификатор заказа
        current_user: Текущий авторизованный пользователь
        db: Сессия базы данных
    
    Returns:
        OrderResponse: Детали заказа
    
    Raises:
        HTTPException 404: Заказ не найден
        HTTPException 403: Нет доступа к заказу
    """
    # Получаем заказ из базы данных
    order = db.query(Order).filter(Order.id == order_id).first()
    
    # Проверяем существование заказа
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Заказ с ID {order_id} не найден"
        )
    
    # Проверяем права доступа пользователя к заказу
    if not check_order_access(current_user, order):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="У вас нет доступа к этому заказу"
        )
    
    # Конвертируем модель в схему ответа
    order_response = OrderResponse.from_orm(order)
    
    # Логируем успешный запрос (опционально)
    # await log_access(db, current_user.id, f"get_order_{order_id}")
    
    return order_response