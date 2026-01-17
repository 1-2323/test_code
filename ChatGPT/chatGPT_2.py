from typing import Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel


# =========================
# Pydantic-модели
# =========================

class User(BaseModel):
    """
    Модель текущего пользователя,
    получаемого из сессии.
    """
    id: int
    username: str
    is_active: bool


class Order(BaseModel):
    """
    Pydantic-модель заказа,
    возвращаемая клиенту API.
    """
    id: int
    user_id: int
    product_name: str
    quantity: int
    total_price: float


# =========================
# Имитация базы данных
# =========================

class FakeOrderDatabase:
    """
    Упрощённая имитация базы данных заказов.
    """

    def __init__(self) -> None:
        self._orders: Dict[int, Dict[str, Any]] = {
            1: {
                "id": 1,
                "user_id": 10,
                "product_name": "Laptop",
                "quantity": 1,
                "total_price": 1200.0,
            },
            2: {
                "id": 2,
                "user_id": 20,
                "product_name": "Mouse",
                "quantity": 2,
                "total_price": 50.0,
            },
        }

    def get_order_by_id(self, order_id: int) -> Optional[Dict[str, Any]]:
        """
        Возвращает заказ по ID или None,
        если заказ не найден.
        """
        return self._orders.get(order_id)


# =========================
# Репозиторий
# =========================

class OrderRepository:
    """
    Репозиторий для работы с заказами.
    Отвечает за получение данных и их преобразование.
    """

    def __init__(self, database: FakeOrderDatabase) -> None:
        self._database: FakeOrderDatabase = database

    def get_order_details(self, order_id: int) -> Order:
        """
        Получает детали заказа из БД и
        преобразует их в Pydantic-модель.

        :param order_id: идентификатор заказа
        :return: объект Order
        :raises HTTPException: если заказ не найден
        """
        order_data: Optional[Dict[str, Any]] = self._database.get_order_by_id(order_id)

        if order_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )

        return Order(**order_data)


# =========================
# Зависимости (Dependencies)
# =========================

def get_current_user() -> User:
    """
    Имитация получения текущего пользователя из сессии.
    В реальном приложении здесь была бы проверка токена
    или данных сессии.
    """
    return User(
        id=10,
        username="john_doe",
        is_active=True,
    )


def get_order_repository() -> OrderRepository:
    """
    Dependency для получения экземпляра OrderRepository.
    """
    database = FakeOrderDatabase()
    return OrderRepository(database=database)


# =========================
# FastAPI-приложение и эндпоинты
# =========================

app = FastAPI(title="Order Service API")


@app.get("/orders/{order_id}", response_model=Order)
def get_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    repository: OrderRepository = Depends(get_order_repository),
) -> Order:
    """
    Эндпоинт получения деталей заказа по ID.

    Алгоритм:
    1. Получаем текущего пользователя из сессии
    2. Запрашиваем данные заказа через репозиторий
    3. Возвращаем Pydantic-модель заказа
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return repository.get_order_details(order_id=order_id)
