from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
import sqlite3
from contextlib import contextmanager

app = FastAPI(title="Order Repository API")

# --- Pydantic модели ---
class OrderItem(BaseModel):
    """Модель товара в заказе."""
    product_id: UUID
    product_name: str
    quantity: int = Field(gt=0)
    price_per_unit: float = Field(gt=0)

class OrderResponse(BaseModel):
    """Модель ответа с деталями заказа."""
    order_id: UUID
    user_id: UUID
    status: str
    total_amount: float
    created_at: datetime
    items: list[OrderItem]
    shipping_address: Optional[str] = None

# --- Имитация аутентификации ---
class CurrentUser:
    """Класс для имитации текущего пользователя."""
    
    def __init__(self):
        # В реальном приложении здесь будет логика получения пользователя из сессии/JWT
        self.user_id = UUID("12345678-1234-1234-1234-123456789abc")
    
    def get_id(self) -> UUID:
        """Получение ID текущего пользователя."""
        return self.user_id

def get_current_user() -> CurrentUser:
    """Зависимость FastAPI для получения текущего пользователя."""
    return CurrentUser()

# --- Database Layer ---
class DatabaseManager:
    """Менеджер для работы с базой данных."""
    
    def __init__(self, db_path: str = "orders.db"):
        self.db_path = db_path
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для подключения к БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Для доступа к полям по имени
        try:
            yield conn
        finally:
            conn.close()
    
    def init_database(self):
        """Инициализация базы данных (для демонстрации)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Создаем таблицу заказов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_amount REAL NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    shipping_address TEXT
                )
            """)
            
            # Создаем таблицу товаров в заказах
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price_per_unit REAL NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES orders(order_id)
                )
            """)
            conn.commit()

# --- Repository Layer ---
class OrderRepository:
    """Репозиторий для работы с заказами."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def get_order_by_id(self, order_id: UUID, user_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Получение заказа по ID с проверкой принадлежности пользователю.
        
        Args:
            order_id: UUID заказа
            user_id: UUID пользователя
            
        Returns:
            Словарь с данными заказа или None если заказ не найден
            
        Raises:
            HTTPException: Если заказ не принадлежит пользователю
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # ПАРАМЕТРИЗОВАННЫЙ ЗАПРОС для предотвращения SQL-инъекций
                cursor.execute("""
                    SELECT o.*, 
                           json_group_array(
                               json_object(
                                   'product_id', oi.product_id,
                                   'product_name', oi.product_name,
                                   'quantity', oi.quantity,
                                   'price_per_unit', oi.price_per_unit
                               )
                           ) as items_json
                    FROM orders o
                    LEFT JOIN order_items oi ON o.order_id = oi.order_id
                    WHERE o.order_id = ?
                    GROUP BY o.order_id
                """, (str(order_id),))
                
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                # Проверяем принадлежность заказа пользователю
                if row['user_id'] != str(user_id):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Доступ к заказу запрещен"
                    )
                
                # Преобразуем данные
                order_data = dict(row)
                
                # Парсим JSON с товарами
                import json
                order_data['items'] = json.loads(row['items_json']) if row['items_json'] else []
                del order_data['items_json']
                
                # Конвертируем строки в UUID
                order_data['order_id'] = UUID(order_data['order_id'])
                order_data['user_id'] = UUID(order_data['user_id'])
                
                return order_data
                
        except HTTPException:
            raise
        except Exception as e:
            print(f"Database error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ошибка при получении заказа"
            )

# --- API Endpoints ---
db_manager = DatabaseManager()
order_repo = OrderRepository(db_manager)

# Инициализируем БД при старте
@app.on_event("startup")
async def startup_event():
    db_manager.init_database()

@app.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order_details(
    order_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
) -> OrderResponse:
    """
    Эндпоинт для получения деталей заказа.
    
    Args:
        order_id: ID заказа
        current_user: Текущий пользователь из сессии
        
    Returns:
        Детали заказа в формате OrderResponse
        
    Raises:
        HTTPException: Если заказ не найден или нет доступа
    """
    # Получаем данные заказа
    order_data = order_repo.get_order_by_id(order_id, current_user.get_id())
    
    if not order_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Заказ не найден"
        )
    
    # Преобразуем в Pydantic модель
    return OrderResponse(**order_data)

# --- Тестовые данные ---
@app.on_event("startup")
async def add_test_data():
    """Добавление тестовых данных (для демонстрации)."""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Тестовый заказ
            test_order_id = "11111111-1111-1111-1111-111111111111"
            test_user_id = "12345678-1234-1234-1234-123456789abc"
            
            # Проверяем, есть ли уже тестовые данные
            cursor.execute("SELECT COUNT(*) FROM orders WHERE order_id = ?", 
                          (test_order_id,))
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO orders (order_id, user_id, status, total_amount, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (test_order_id, test_user_id, "completed", 2999.99, datetime.now()))
                
                cursor.execute("""
                    INSERT INTO order_items (order_id, product_id, product_name, quantity, price_per_unit)
                    VALUES (?, ?, ?, ?, ?)
                """, (test_order_id, "22222222-2222-2222-2222-222222222222", 
                      "Ноутбук", 1, 2499.99))
                
                cursor.execute("""
                    INSERT INTO order_items (order_id, product_id, product_name, quantity, price_per_unit)
                    VALUES (?, ?, ?, ?, ?)
                """, (test_order_id, "33333333-3333-3333-3333-333333333333", 
                      "Мышь", 1, 500.0))
                
                conn.commit()
                print("Тестовые данные добавлены")
                
    except Exception as e:
        print(f"Ошибка при добавлении тестовых данных: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)