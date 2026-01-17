import sqlite3
from typing import Optional, Dict, Any, Final
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict

# --- Модели данных (Pydantic) ---

class OrderSchema(BaseModel):
    """Схема для валидации и сериализации данных заказа."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    product_name: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    status: str

class User(BaseModel):
    """Схема текущего пользователя."""
    id: int
    username: str

# --- Имитация безопасности и зависимостей ---

async def get_current_user() -> User:
    """
    Имитирует получение текущего пользователя из сессии/JWT.
    В реальном приложении здесь была бы проверка токена.
    """
    return User(id=42, username="john_doe")

# --- Репозиторий для работы с БД ---

class OrderRepository:
    """Репозиторий для безопасного управления данными заказов."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path: str = db_path
        self._init_mock_db()

    def _init_mock_db(self) -> None:
        """Инициализация временной БД и наполнение тестовыми данными."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, product_name TEXT, amount REAL, status TEXT)"
            )
            # Тестовый заказ, принадлежащий пользователю 42
            conn.execute(
                "INSERT INTO orders (id, user_id, product_name, amount, status) VALUES (?, ?, ?, ?, ?)",
                (1, 42, "Laptop Pro", 1500.0, "shipped")
            )
            # Тестовый заказ чужого пользователя
            conn.execute(
                "INSERT INTO orders (id, user_id, product_name, amount, status) VALUES (?, ?, ?, ?, ?)",
                (2, 99, "Secret Phone", 800.0, "pending")
            )

    def get_order_by_id(self, order_id: int, owner_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает детали заказа с проверкой владельца через параметризованный запрос.
        
        :param order_id: Уникальный идентификатор заказа.
        :param owner_id: ID пользователя, запрашивающего данные.
        :return: Словарь с данными заказа или None.
        """
        query: Final[str] = "SELECT id, user_id, product_name, amount, status FROM orders WHERE id = ? AND user_id = ?"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, (order_id, owner_id))
            row = cursor.fetchone()
            return dict(row) if row else None

# --- Инициализация API ---

app = FastAPI(title="Order Management System")
order_repo = OrderRepository()

@app.get("/orders/{order_id}", response_model=OrderSchema)
async def read_order_details(
    order_id: int, 
    current_user: User = Depends(get_current_user)
) -> OrderSchema:
    """
    Эндпоинт для получения деталей заказа.
    Проверяет существование заказа и права доступа пользователя.
    """
    order_data = order_repo.get_order_by_id(order_id, current_user.id)

    if not order_data:
        # Унифицированное сообщение об ошибке для безопасности (не раскрываем, существует ли ID)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found or access denied."
        )

    return OrderSchema(**order_data)