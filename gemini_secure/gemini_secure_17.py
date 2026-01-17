from typing import List, Dict, Any, Final
from decimal import Decimal
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship
from pydantic import BaseModel, Field, ConfigDict

# --- Определение моделей БД ---
Base = declarative_base()

class Product(Base):
    """Модель каталога товаров."""
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)  # Актуальная цена в БД

class Order(Base):
    """Модель основного заказа."""
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    total_amount = Column(Numeric(10, 2), nullable=False)
    items = relationship("OrderItem", back_populates="order")

class OrderItem(Base):
    """Детализация позиций заказа."""
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer, nullable=False)
    price_at_checkout = Column(Numeric(10, 2), nullable=False)
    order = relationship("Order", back_populates="items")

# --- Схемы валидации (Pydantic) ---

class ItemRequest(BaseModel):
    """Запрос на добавление товара в корзину."""
    product_id: int
    quantity: int = Field(..., gt=0, le=100)

class CheckoutRequest(BaseModel):
    """Входящие данные от клиента."""
    items: List[ItemRequest] = Field(..., min_length=1)

# --- Сервис оформления заказа ---

class CheckoutProcessor:
    """
    Сервис обработки заказов с гарантией целостности данных 
    и расчетом стоимости на стороне сервера.
    """

    def __init__(self, db_url: str = "sqlite+aiosqlite:///:memory:"):
        self.engine = create_async_engine(db_url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init_db(self) -> None:
        """Инициализация таблиц БД."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def process_checkout(self, checkout_data: CheckoutRequest) -> Dict[str, Any]:
        """
        Основная логика оформления заказа в рамках атомарной транзакции.
        """
        async with self.session_factory() as session:
            # Используем begin() для автоматического управления транзакцией (commit/rollback)
            async with session.begin():
                # 1. Сбор всех ID товаров для пакетного запроса
                product_ids = [item.product_id for item in checkout_data.items]
                
                # 2. Получение актуальных цен из БД (игнорируем ввод клиента)
                stmt = select(Product).where(Product.id.in_(product_ids))
                result = await session.execute(stmt)
                catalog: Dict[int, Product] = {p.id: p for p in result.scalars().all()}

                # Проверка существования всех товаров
                if len(catalog) != len(set(product_ids)):
                    raise ValueError("One or more products not found in catalog.")

                # 3. Расчет итоговой суммы и создание позиций
                total_sum = Decimal("0.00")
                order_items: List[OrderItem] = []

                for item in checkout_data.items:
                    product = catalog[item.product_id]
                    line_price = product.price * item.quantity
                    total_sum += line_price
                    
                    order_items.append(OrderItem(
                        product_id=product.id,
                        quantity=item.quantity,
                        price_at_checkout=product.price
                    ))

                # 4. Сохранение заказа
                new_order = Order(total_amount=total_sum, items=order_items)
                session.add(new_order)
                
                # Важно: commit произойдет автоматически при выходе из контекста session.begin()
                # Если возникнет ошибка на любом этапе, изменения не будут применены.
                
                await session.flush() # Получаем ID заказа до коммита
                
                return {
                    "order_id": new_order.id,
                    "total_amount": float(total_sum),
                    "status": "created"
                }

# --- Пример интеграции с FastAPI ---

from fastapi import FastAPI, HTTPException

app = FastAPI()
processor = CheckoutProcessor()

@app.post("/checkout")
async def create_order(request: CheckoutRequest):
    """Эндпоинт оформления заказа."""
    try:
        result = await processor.process_checkout(request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Transaction failed. Please try again.")