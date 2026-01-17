from datetime import datetime
from typing import List

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field, conint
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    DateTime,
    create_engine,
)
from sqlalchemy.orm import (
    declarative_base,
    relationship,
    sessionmaker,
    Session,
)


# =========================
# Конфигурация БД
# =========================

DATABASE_URL: str = "sqlite:///./shop.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# =========================
# ORM-модели
# =========================

class Product(Base):
    """
    Каталог товаров.
    """
    __tablename__ = "products"

    id: int = Column(Integer, primary_key=True)
    name: str = Column(String, nullable=False)
    price: float = Column(Float, nullable=False)


class Order(Base):
    """
    Заказ пользователя.
    """
    __tablename__ = "orders"

    id: int = Column(Integer, primary_key=True)
    total_amount: float = Column(Float, nullable=False)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)

    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    """
    Позиция заказа.
    """
    __tablename__ = "order_items"

    id: int = Column(Integer, primary_key=True)
    order_id: int = Column(Integer, ForeignKey("orders.id"))
    product_id: int = Column(Integer, ForeignKey("products.id"))
    quantity: int = Column(Integer, nullable=False)
    price_at_purchase: float = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")


# =========================
# Pydantic-модели
# =========================

class CheckoutItem(BaseModel):
    """
    Входная позиция заказа.
    """
    product_id: int
    quantity: conint(gt=0)


class CheckoutRequest(BaseModel):
    """
    Запрос оформления заказа.
    """
    items: List[CheckoutItem] = Field(..., min_items=1)


class OrderResponse(BaseModel):
    """
    Ответ API при создании заказа.
    """
    order_id: int
    total_amount: float


# =========================
# Репозитории
# =========================

class ProductRepository:
    """
    Репозиторий товаров.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, product_id: int) -> Product:
        product = self._db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return product


class OrderRepository:
    """
    Репозиторий заказов.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, order: Order) -> Order:
        self._db.add(order)
        self._db.commit()
        self._db.refresh(order)
        return order


# =========================
# Сервис оформления заказа
# =========================

class CheckoutProcessor:
    """
    Сервис оформления заказа.
    """

    def __init__(
        self,
        product_repository: ProductRepository,
        order_repository: OrderRepository,
    ) -> None:
        self._products = product_repository
        self._orders = order_repository

    def process(self, items: List[CheckoutItem]) -> Order:
        """
        Основной алгоритм checkout:
        1. Получение актуальных цен
        2. Расчёт итоговой суммы
        3. Создание заказа и позиций
        """
        total_amount: float = 0.0
        order_items: List[OrderItem] = []

        for item in items:
            product = self._products.get_by_id(item.product_id)
            line_total = product.price * item.quantity
            total_amount += line_total

            order_items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=item.quantity,
                    price_at_purchase=product.price,
                )
            )

        order = Order(
            total_amount=total_amount,
            items=order_items,
        )

        return self._orders.create(order)


# =========================
# Dependency
# =========================

def get_db() -> Session:
    """
    Dependency для получения сессии БД.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================
# FastAPI-приложение
# =========================

app = FastAPI(title="Checkout Service")


@app.post("/checkout", response_model=OrderResponse)
def checkout(
    request: CheckoutRequest,
    db: Session = Depends(get_db),
) -> OrderResponse:
    """
    Эндпоинт оформления заказа.
    """
    product_repo = ProductRepository(db)
    order_repo = OrderRepository(db)
    processor = CheckoutProcessor(product_repo, order_repo)

    order = processor.process(request.items)

    return OrderResponse(
        order_id=order.id,
        total_amount=order.total_amount,
    )


# =========================
# Инициализация БД
# =========================

def init_database() -> None:
    """
    Создаёт таблицы БД.
    """
    Base.metadata.create_all(bind=engine)
