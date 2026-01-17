from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel
import sqlite3


# =========================
# МОДЕЛИ ДАННЫХ
# =========================

class User(BaseModel):
    """
    Модель текущего пользователя,
    получаемого из сессии.
    """
    id: int
    username: str


class OrderModel(BaseModel):
    """
    Pydantic-модель заказа,
    возвращаемая клиенту.
    """
    id: int
    user_id: int
    product_name: str
    quantity: int
    price: float


# =========================
# ИМИТАЦИЯ СЕССИИ
# =========================

def get_current_user() -> User:
    """
    Имитирует получение текущего пользователя из сессии.
    В реальном приложении здесь была бы JWT / OAuth / Session логика.
    """
    return User(id=1, username="test_user")


# =========================
# РЕПОЗИТОРИЙ
# =========================

class OrderRepository:
    """
    Репозиторий для работы с заказами.
    Инкапсулирует доступ к базе данных.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection: sqlite3.Connection = connection

    def get_order_by_id(
        self,
        order_id: int,
        current_user: User
    ) -> OrderModel:
        """
        Получает заказ по ID, проверяя,
        что он принадлежит текущему пользователю.

        :param order_id: ID заказа
        :param current_user: текущий пользователь
        :return: OrderModel
        """
        query: str = """
            SELECT id, user_id, product_name, quantity, price
            FROM orders
            WHERE id = ? AND user_id = ?
        """

        cursor = self._connection.cursor()
        cursor.execute(query, (order_id, current_user.id))
        row = cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Заказ не найден или не принадлежит пользователю"
            )

        return OrderModel(
            id=row[0],
            user_id=row[1],
            product_name=row[2],
            quantity=row[3],
            price=row[4],
        )


# =========================
# ИНИЦИАЛИЗАЦИЯ БД
# =========================

def get_database_connection() -> sqlite3.Connection:
    """
    Создаёт соединение с БД.
    Используется SQLite для простоты примера.
    """
    connection = sqlite3.connect(
        "orders.db",
        check_same_thread=False
    )
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """
    Создаёт таблицу и тестовые данные,
    если БД пустая.
    """
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL
        )
        """
    )

    cursor.execute(
        """
        INSERT OR IGNORE INTO orders (id, user_id, product_name, quantity, price)
        VALUES
            (1, 1, 'Laptop', 1, 1200.00),
            (2, 1, 'Mouse', 2, 25.50),
            (3, 2, 'Keyboard', 1, 75.00)
        """
    )

    connection.commit()


# =========================
# FASTAPI ПРИЛОЖЕНИЕ
# =========================

app = FastAPI(
    title="Order Service",
    description="Сервис получения заказов пользователя",
    version="1.0.0",
)

db_connection: sqlite3.Connection = get_database_connection()
initialize_database(db_connection)

order_repository = OrderRepository(db_connection)


# =========================
# ENDPOINT
# =========================

@app.get(
    "/orders/{order_id}",
    response_model=OrderModel,
    summary="Получить детали заказа",
)
def get_order_details(
    order_id: int,
    current_user: User = Depends(get_current_user),
) -> OrderModel:
    """
    HTTP-эндпоинт для получения деталей заказа.

    Проверяет, что заказ принадлежит текущему пользователю.
    """
    return order_repository.get_order_by_id(
        order_id=order_id,
        current_user=current_user,
    )
