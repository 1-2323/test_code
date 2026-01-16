"""
Модуль для работы с заказами на FastAPI с использованием Pydantic моделей.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, Field, validator
import sqlite3


# ==================== МОДЕЛИ ДАННЫХ ====================

class OrderStatus(str, Enum):
    """Статусы заказа."""
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class OrderItemDB(BaseModel):
    """Модель для товара в заказе (из БД)."""
    product_id: int
    product_name: str
    quantity: int
    unit_price: float
    total_price: float = Field(..., description="Вычисляемое поле: quantity * unit_price")
    
    @validator('total_price', always=True)
    def calculate_total_price(cls, v, values):
        """Вычисляет общую стоимость позиции."""
        if 'quantity' in values and 'unit_price' in values:
            return values['quantity'] * values['unit_price']
        return v


class OrderDB(BaseModel):
    """Модель заказа из базы данных."""
    id: int
    user_id: int
    order_number: str
    status: OrderStatus
    total_amount: float
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: List[OrderItemDB] = Field(default_factory=list)


class OrderResponse(BaseModel):
    """Pydantic модель для ответа API (сериализация заказа)."""
    id: int
    order_number: str
    status: OrderStatus
    total_amount: float = Field(..., ge=0, description="Общая сумма заказа")
    created_at: datetime
    updated_at: Optional[datetime]
    items_count: int = Field(..., description="Количество товаров в заказе")
    items: List[OrderItemDB]
    
    class Config:
        """Конфигурация Pydantic модели."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "id": 1,
                "order_number": "ORD-2024-001",
                "status": "processing",
                "total_amount": 199.99,
                "created_at": "2024-01-15T10:30:00",
                "updated_at": "2024-01-15T11:00:00",
                "items_count": 2,
                "items": [
                    {
                        "product_id": 101,
                        "product_name": "Продукт A",
                        "quantity": 1,
                        "unit_price": 99.99,
                        "total_price": 99.99
                    }
                ]
            }
        }


# ==================== СЛУЖЕБНЫЕ КЛАССЫ ====================

@dataclass
class CurrentUser:
    """Модель текущего пользователя (имитация сессии/аутентификации)."""
    id: int
    username: str
    email: str
    is_active: bool = True


class DatabaseConnection:
    """Контекстный менеджер для подключения к БД."""
    
    def __init__(self, db_path: str = "orders.db"):
        self.db_path = db_path
    
    def __enter__(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        return self.conn
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()


class OrderRepository:
    """Репозиторий для работы с заказами в базе данных."""
    
    def __init__(self, db_path: str = "orders.db"):
        """
        Инициализация репозитория заказов.
        
        Args:
            db_path: Путь к файлу базы данных SQLite.
        """
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self) -> None:
        """Инициализирует таблицы базы данных, если они не существуют."""
        with DatabaseConnection(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица заказов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    order_number TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    total_amount REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            
            # Таблица товаров в заказах
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES orders (id)
                )
            ''')
            
            conn.commit()
    
    def get_order_by_id(self, order_id: int, user_id: Optional[int] = None) -> Optional[OrderDB]:
        """
        Получает заказ по ID с опциональной проверкой принадлежности пользователю.
        
        Args:
            order_id: ID заказа.
            user_id: ID пользователя для проверки прав доступа.
            
        Returns:
            OrderDB если заказ найден, None если не найден.
            
        Raises:
            HTTPException: Если заказ не принадлежит пользователю.
        """
        with DatabaseConnection(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Основной запрос заказа
            query = """
                SELECT o.*, 
                       oi.product_id, oi.product_name, oi.quantity, oi.unit_price
                FROM orders o
                LEFT JOIN order_items oi ON o.id = oi.order_id
                WHERE o.id = ?
            """
            
            params = [order_id]
            
            # Добавляем проверку пользователя, если указан
            if user_id is not None:
                query += " AND o.user_id = ?"
                params.append(user_id)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            if not rows:
                return None
            
            # Собираем данные заказа
            order_data = dict(rows[0])
            items = []
            
            for row in rows:
                if row['product_id']:  # Если есть товары
                    item = OrderItemDB(
                        product_id=row['product_id'],
                        product_name=row['product_name'],
                        quantity=row['quantity'],
                        unit_price=row['unit_price']
                    )
                    items.append(item)
            
            # Преобразуем статус из строки в enum
            try:
                status = OrderStatus(order_data['status'])
            except ValueError:
                status = OrderStatus.PENDING
            
            return OrderDB(
                id=order_data['id'],
                user_id=order_data['user_id'],
                order_number=order_data['order_number'],
                status=status,
                total_amount=order_data['total_amount'],
                created_at=datetime.fromisoformat(order_data['created_at']),
                updated_at=datetime.fromisoformat(order_data['updated_at']) if order_data['updated_at'] else None,
                items=items
            )


# ==================== ЗАВИСИМОСТИ FASTAPI ====================

def get_current_user() -> CurrentUser:
    """
    Зависимость для имитации получения текущего пользователя из сессии.
    В реальном приложении здесь была бы аутентификация через JWT, cookies и т.д.
    
    Returns:
        CurrentUser: Модель текущего пользователя.
    """
    # Имитация аутентифицированного пользователя
    # В реальном приложении здесь был бы код валидации токена
    return CurrentUser(
        id=1,
        username="john_doe",
        email="john@example.com"
    )


def get_order_repository() -> OrderRepository:
    """
    Зависимость для получения экземпляра OrderRepository.
    
    Returns:
        OrderRepository: Экземпляр репозитория заказов.
    """
    return OrderRepository()


# ==================== FASTAPI ПРИЛОЖЕНИЕ ====================

app = FastAPI(
    title="Order Management API",
    description="API для управления заказами с проверкой прав доступа",
    version="1.0.0"
)


@app.get("/")
async def root():
    """Корневой эндпоинт для проверки работы API."""
    return {
        "message": "Order Management API",
        "version": "1.0.0",
        "endpoints": {
            "get_order": "/orders/{order_id}",
            "health": "/health"
        }
    }


@app.get("/health")
async def health_check():
    """Эндпоинт для проверки здоровья сервиса."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="Получить детали заказа",
    description="""Получает детальную информацию о заказе по его ID.
    Проверяет права доступа текущего пользователя.""",
    responses={
        200: {"description": "Заказ успешно получен"},
        404: {"description": "Заказ не найден"},
        403: {"description": "Доступ запрещен"}
    }
)
async def get_order_details(
    order_id: int = Field(..., gt=0, description="ID заказа"),
    current_user: CurrentUser = Depends(get_current_user),
    order_repo: OrderRepository = Depends(get_order_repository)
) -> OrderResponse:
    """
    Получает детали заказа по ID с проверкой прав доступа.
    
    Args:
        order_id: ID заказа для получения.
        current_user: Текущий аутентифицированный пользователь.
        order_repo: Репозиторий для работы с заказами.
        
    Returns:
        OrderResponse: Детали заказа в формате Pydantic модели.
        
    Raises:
        HTTPException: Если заказ не найден или доступ запрещен.
    """
    try:
        # Получаем заказ с проверкой принадлежности пользователю
        order = order_repo.get_order_by_id(order_id, current_user.id)
        
        if not order:
            # Проверяем, существует ли заказ вообще
            order_without_check = order_repo.get_order_by_id(order_id)
            if order_without_check:
                # Заказ существует, но не принадлежит пользователю
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="У вас нет доступа к этому заказу"
                )
            else:
                # Заказ не существует
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Заказ с ID {order_id} не найден"
                )
        
        # Преобразуем OrderDB в OrderResponse
        return OrderResponse(
            id=order.id,
            order_number=order.order_number,
            status=order.status,
            total_amount=order.total_amount,
            created_at=order.created_at,
            updated_at=order.updated_at,
            items_count=len(order.items),
            items=order.items
        )
        
    except HTTPException:
        # Пробрасываем HTTP исключения дальше
        raise
    except Exception as e:
        # Логируем внутреннюю ошибку и возвращаем 500
        print(f"Внутренняя ошибка при получении заказа {order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )


# Пример запуска приложения
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)