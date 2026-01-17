from typing import List

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import (
    declarative_base,
    relationship,
    sessionmaker,
    Session,
)
from sqlalchemy.exc import SQLAlchemyError


# =========================
# DATABASE SETUP
# =========================

DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


# =========================
# DATABASE MODELS
# =========================

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    total_amount = Column(Numeric(10, 2), nullable=False)

    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price_at_purchase = Column(Numeric(10, 2), nullable=False)

    order = relationship("Order", back_populates="items")


Base.metadata.create_all(engine)


# =========================
# Pydantic SCHEMAS
# =========================

class CheckoutItem(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=100)

    model_config = ConfigDict(extra="forbid")


class CheckoutRequest(BaseModel):
    items: List[CheckoutItem] = Field(min_length=1, max_length=50)

    model_config = ConfigDict(extra="forbid")


class CheckoutResponse(BaseModel):
    order_id: int
    total_amount: float


# =========================
# REPOSITORY
# =========================

class ProductRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_products_by_ids(self, product_ids: List[int]) -> List[Product]:
        return (
            self._db.query(Product)
            .filter(Product.id.in_(product_ids))
            .all()
        )


class OrderRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_order(self, order: Order) -> None:
        self._db.add(order)


# =========================
# CHECKOUT PROCESSOR
# =========================

class CheckoutProcessor:
    """
    Логика оформления заказа.
    Итоговая стоимость рассчитывается исключительно по данным БД.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._product_repo = ProductRepository(db)
        self._order_repo = OrderRepository(db)

    def process_checkout(self, request: CheckoutRequest) -> Order:
        product_ids = [item.product_id for item in request.items]
        products = self._product_repo.get_products_by_ids(product_ids)

        if len(products) != len(set(product_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Один или несколько товаров не найдены",
            )

        product_map = {product.id: product for product in products}

        order = Order(total_amount=0)
        total_amount = 0

        for item in request.items:
            product = product_map[item.product_id]
            item_total = product.price * item.quantity
            total_amount += item_total

            order_item = OrderItem(
                product_id=product.id,
                quantity=item.quantity,
                price_at_purchase=product.price,
            )
            order.items.append(order_item)

        order.total_amount = total_amount
        self._order_repo.create_order(order)

        return order


# =========================
# FASTAPI APPLICATION
# =========================

app = FastAPI(
    title="Checkout Service",
    version="1.0.0",
    description="Оформление заказов",
)


# =========================
# ENDPOINT
# =========================

@app.post(
    "/checkout",
    response_model=CheckoutResponse,
)
def checkout(request: CheckoutRequest) -> CheckoutResponse:
    db = SessionLocal()
    try:
        with db.begin():
            processor = CheckoutProcessor(db)
            order = processor.process_checkout(request)

        return CheckoutResponse(
            order_id=order.id,
            total_amount=float(order.total_amount),
        )
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка оформления заказа",
        )
    finally:
        db.close()
