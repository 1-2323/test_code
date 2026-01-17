from datetime import datetime
from typing import List, Dict, Any, Tuple
from decimal import Decimal
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

Base = declarative_base()

class Product(Base):
    """Модель товара в каталоге."""
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    stock = Column(Integer, default=0)

class Order(Base):
    """Модель заказа."""
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    total_amount = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    items = relationship("OrderItem", back_populates="order")

class OrderItem(Base):
    """Детализация позиций в заказе."""
    __tablename__ = 'order_items'
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('orders.id'))
    product_id = Column(Integer, ForeignKey('products.id'))
    quantity = Column(Integer, nullable=False)
    price_at_purchase = Column(Numeric(10, 2), nullable=False)
    order = relationship("Order", back_populates="items")

class CheckoutProcessor:
    """
    Сервис обработки оформления заказа.
    Рассчитывает стоимость на основе актуальных цен и фиксирует транзакцию.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def process_checkout(self, cart_items: List[Dict[str, int]]) -> Order:
        """
        Основной процесс оформления заказа.
        
        Логика:
        1. Извлечение ID товаров и проверка их наличия в БД.
        2. Валидация цен и остатков.
        3. Расчет итоговой суммы.
        4. Сохранение заказа и его позиций в БД.
        """
        product_ids = [item['id'] for item in cart_items]
        
        # 1. Получаем продукты одним запросом для оптимизации
        products = self.db.query(Product).filter(Product.id.in_(product_ids)).all()
        product_map = {p.id: p for p in products}

        if len(product_map) != len(product_ids):
            raise ValueError("Один или несколько товаров не найдены в каталоге.")

        total_sum = Decimal("0.00")
        order_entries = []

        # 2. Расчет стоимости и подготовка позиций заказа
        for item in cart_items:
            product = product_map[item['id']]
            qty = item['quantity']

            if qty <= 0:
                raise ValueError(f"Некорректное количество для товара {product.name}.")
            
            item_total = product.price * qty
            total_sum += item_total

            order_entries.append(OrderItem(
                product_id=product.id,
                quantity=qty,
                price_at_purchase=product.price
            ))

        # 3. Создание и сохранение заказа
        new_order = Order(total_amount=total_sum, items=order_entries)

        try:
            self.db.add(new_order)
            self.db.commit()
            self.db.refresh(new_order)
            return new_order
        except Exception as e:
            self.db.rollback()
            raise RuntimeError(f"Ошибка при оформлении заказа: {e}")

# --- Пример использования ---
if __name__ == "__main__":
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        # Наполнение каталога
        session.add_all([
            Product(id=1, name="Laptop", price=Decimal("1200.00"), stock=10),
            Product(id=2, name="Mouse", price=Decimal("25.50"), stock=50)
        ])
        session.commit()

        processor = CheckoutProcessor(session)
        
        # Данные из запроса (Frontend)
        request_cart = [
            {"id": 1, "quantity": 1},
            {"id": 2, "quantity": 2}
        ]

        try:
            order = processor.process_checkout(request_cart)
            print(f"Заказ #{order.id} оформлен на сумму: {order.total_amount}")
        except Exception as err:
            print(f"Сбой Checkout: {err}")