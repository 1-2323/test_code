from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from abc import ABC, abstractmethod
import uuid


@dataclass
class CartItem:
    """Представление товара в корзине"""
    product_id: str
    quantity: int


@dataclass
class ProductInfo:
    """Информация о товаре из каталога"""
    product_id: str
    name: str
    price: Decimal
    available_quantity: int
    is_active: bool


@dataclass
class OrderItem:
    """Элемент заказа"""
    product_id: str
    product_name: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal


@dataclass
class Order:
    """Заказ"""
    order_id: str
    user_id: str
    items: List[OrderItem]
    total_amount: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


class ProductCatalogRepository(ABC):
    """Абстрактный репозиторий для работы с каталогом товаров"""
    
    @abstractmethod
    def get_products_info(self, product_ids: List[str]) -> List[ProductInfo]:
        """Получить информацию о товарах по их ID"""
        pass
    
    @abstractmethod
    def update_product_quantity(self, product_id: str, quantity: int) -> bool:
        """Обновить количество товара на складе"""
        pass


class OrderRepository(ABC):
    """Абстрактный репозиторий для работы с заказами"""
    
    @abstractmethod
    def save_order(self, order: Order) -> bool:
        """Сохранить заказ в базу данных"""
        pass
    
    @abstractmethod
    def create_order_id(self) -> str:
        """Сгенерировать уникальный ID заказа"""
        pass


class CheckoutProcessor:
    """Процессор оформления заказа"""
    
    def __init__(
        self,
        product_repo: ProductCatalogRepository,
        order_repo: OrderRepository,
        tax_rate: Decimal = Decimal('0.20')  # НДС 20%
    ):
        self.product_repo = product_repo
        self.order_repo = order_repo
        self.tax_rate = tax_rate
    
    def process_checkout(
        self,
        user_id: str,
        cart_items: List[CartItem]
    ) -> Tuple[bool, Optional[Order], str]:
        """
        Обработать оформление заказа
        
        Args:
            user_id: Идентификатор пользователя
            cart_items: Список товаров в корзине
            
        Returns:
            Tuple[успех, заказ или None, сообщение]
        """
        try:
            # 1. Валидация входных данных
            validation_result = self._validate_cart_items(cart_items)
            if not validation_result[0]:
                return False, None, validation_result[1]
            
            # 2. Получение актуальной информации о товарах
            product_ids = [item.product_id for item in cart_items]
            products_info = self.product_repo.get_products_info(product_ids)
            
            # 3. Проверка наличия и доступности товаров
            availability_check = self._check_products_availability(
                cart_items, products_info
            )
            if not availability_check[0]:
                return False, None, availability_check[1]
            
            # 4. Создание элементов заказа
            order_items, total_amount = self._create_order_items(
                cart_items, products_info
            )
            
            # 5. Добавление налогов
            total_with_tax = self._calculate_total_with_tax(total_amount)
            
            # 6. Создание заказа
            order = self._create_order(user_id, order_items, total_with_tax)
            
            # 7. Сохранение заказа
            if self.order_repo.save_order(order):
                # 8. Обновление остатков на складе
                self._update_inventory(cart_items)
                
                return True, order, "Заказ успешно оформлен"
            else:
                return False, None, "Ошибка при сохранении заказа"
                
        except Exception as e:
            return False, None, f"Ошибка при оформлении заказа: {str(e)}"
    
    def _validate_cart_items(
        self, 
        cart_items: List[CartItem]
    ) -> Tuple[bool, str]:
        """Проверка валидности товаров в корзине"""
        if not cart_items:
            return False, "Корзина пуста"
        
        for item in cart_items:
            if item.quantity <= 0:
                return False, f"Некорректное количество для товара {item.product_id}"
            
            if not item.product_id:
                return False, "Обнаружен товар без ID"
        
        return True, ""
    
    def _check_products_availability(
        self,
        cart_items: List[CartItem],
        products_info: List[ProductInfo]
    ) -> Tuple[bool, str]:
        """Проверка доступности товаров"""
        product_info_map = {
            info.product_id: info for info in products_info
        }
        
        for item in cart_items:
            product_info = product_info_map.get(item.product_id)
            
            if not product_info:
                return False, f"Товар {item.product_id} не найден"
            
            if not product_info.is_active:
                return False, f"Товар {product_info.name} недоступен"
            
            if product_info.available_quantity < item.quantity:
                return (
                    False,
                    f"Недостаточно товара {product_info.name}. "
                    f"Доступно: {product_info.available_quantity}"
                )
        
        return True, ""
    
    def _create_order_items(
        self,
        cart_items: List[CartItem],
        products_info: List[ProductInfo]
    ) -> Tuple[List[OrderItem], Decimal]:
        """Создание элементов заказа и расчет суммы"""
        order_items = []
        total_amount = Decimal('0')
        
        product_info_map = {
            info.product_id: info for info in products_info
        }
        
        for item in cart_items:
            product_info = product_info_map[item.product_id]
            item_total = product_info.price * item.quantity
            
            order_item = OrderItem(
                product_id=item.product_id,
                product_name=product_info.name,
                quantity=item.quantity,
                unit_price=product_info.price,
                total_price=item_total
            )
            
            order_items.append(order_item)
            total_amount += item_total
        
        return order_items, total_amount
    
    def _calculate_total_with_tax(self, subtotal: Decimal) -> Decimal:
        """Расчет итоговой суммы с налогом"""
        tax_amount = subtotal * self.tax_rate
        return subtotal + tax_amount
    
    def _create_order(
        self,
        user_id: str,
        order_items: List[OrderItem],
        total_amount: Decimal
    ) -> Order:
        """Создание объекта заказа"""
        now = datetime.now()
        order_id = self.order_repo.create_order_id()
        
        return Order(
            order_id=order_id,
            user_id=user_id,
            items=order_items,
            total_amount=total_amount,
            status="created",
            created_at=now,
            updated_at=now
        )
    
    def _update_inventory(self, cart_items: List[CartItem]) -> None:
        """Обновление остатков товаров на складе"""
        for item in cart_items:
            self.product_repo.update_product_quantity(
                product_id=item.product_id,
                quantity=-item.quantity  # Уменьшаем остаток
            )


# Пример использования
if __name__ == "__main__":
    # Заглушки для примера
    class MockProductCatalogRepository(ProductCatalogRepository):
        def get_products_info(self, product_ids: List[str]) -> List[ProductInfo]:
            products = []
            for pid in product_ids:
                products.append(ProductInfo(
                    product_id=pid,
                    name=f"Товар {pid}",
                    price=Decimal('100.50'),
                    available_quantity=10,
                    is_active=True
                ))
            return products
        
        def update_product_quantity(self, product_id: str, quantity: int) -> bool:
            print(f"Обновлен остаток товара {product_id} на {quantity}")
            return True
    
    class MockOrderRepository(OrderRepository):
        def save_order(self, order: Order) -> bool:
            print(f"Заказ сохранен: {order.order_id}")
            return True
        
        def create_order_id(self) -> str:
            return f"ORD-{uuid.uuid4().hex[:8].upper()}"
    
    # Создаем процессор
    checkout_processor = CheckoutProcessor(
        product_repo=MockProductCatalogRepository(),
        order_repo=MockOrderRepository()
    )
    
    # Пример оформления заказа
    cart_items = [
        CartItem(product_id="prod1", quantity=2),
        CartItem(product_id="prod2", quantity=1)
    ]
    
    success, order, message = checkout_processor.process_checkout(
        user_id="user123",
        cart_items=cart_items
    )
    
    if success:
        print(f"Заказ оформлен: {order.order_id}")
        print(f"Сумма: {order.total_amount}")
    else:
        print(f"Ошибка: {message}")