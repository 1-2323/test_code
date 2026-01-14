from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid
import os
from decimal import Decimal

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///shop.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Модель товара
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    sku = db.Column(db.String(50), unique=True)

# Модель заказа
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)  # ID пользователя из системы аутентификации
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(50), default='pending')  # pending, paid, processing, shipped, completed, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    shipping_address = db.Column(db.Text)
    payment_method = db.Column(db.String(100))
    
    # Связь с OrderItem
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

# Модель элемента заказа
class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Связь с Product
    product = db.relationship('Product')

@app.route('/checkout', methods=['POST'])
def checkout():
    """
    Эндпоинт для создания заказа из корзины
    """
    try:
        # В реальном приложении здесь должна быть аутентификация
        # user_id = get_current_user_id()
        # Для примера используем заглушку
        user_id = 1
        
        data = request.get_json()
        
        # Валидация входных данных
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        items = data.get('items')
        client_total_price = data.get('total_price')
        shipping_address = data.get('shipping_address')
        payment_method = data.get('payment_method')
        
        if not items or not isinstance(items, list):
            return jsonify({
                'success': False,
                'error': 'Items list is required and must be an array'
            }), 400
        
        if not client_total_price:
            return jsonify({
                'success': False,
                'error': 'Total price is required'
            }), 400
        
        if not shipping_address:
            return jsonify({
                'success': False,
                'error': 'Shipping address is required'
            }), 400
        
        if not payment_method:
            return jsonify({
                'success': False,
                'error': 'Payment method is required'
            }), 400
        
        # Проверка и обработка товаров
        order_items = []
        calculated_total = Decimal('0.00')
        product_updates = []
        
        for item in items:
            product_id = item.get('product_id')
            quantity = item.get('quantity')
            
            if not product_id or not quantity:
                return jsonify({
                    'success': False,
                    'error': 'Each item must have product_id and quantity'
                }), 400
            
            if quantity <= 0:
                return jsonify({
                    'success': False,
                    'error': f'Invalid quantity for product {product_id}'
                }), 400
            
            # Получаем товар из базы
            product = Product.query.get(product_id)
            if not product:
                return jsonify({
                    'success': False,
                    'error': f'Product {product_id} not found'
                }), 404
            
            # Проверяем наличие на складе
            if product.stock < quantity:
                return jsonify({
                    'success': False,
                    'error': f'Insufficient stock for product: {product.name}. Available: {product.stock}'
                }), 400
            
            # Рассчитываем цены
            unit_price = Decimal(str(product.price))
            item_total = unit_price * quantity
            
            # Подготавливаем данные для OrderItem
            order_item_data = {
                'product_id': product_id,
                'product_name': product.name,
                'quantity': quantity,
                'unit_price': unit_price,
                'total_price': item_total
            }
            order_items.append(order_item_data)
            
            # Обновляем остатки
            product_updates.append({
                'product': product,
                'quantity': quantity
            })
            
            calculated_total += item_total
        
        # Проверка общей суммы
        client_total = Decimal(str(client_total_price))
        
        # Допустимая погрешность в 0.01 из-за округления на клиенте
        if abs(calculated_total - client_total) > Decimal('0.01'):
            return jsonify({
                'success': False,
                'error': f'Price mismatch. Calculated: {calculated_total}, Received: {client_total}'
            }), 400
        
        # Начинаем транзакцию
        db.session.begin_nested()
        
        try:
            # Создаем заказ
            order_number = generate_order_number()
            
            order = Order(
                order_number=order_number,
                user_id=user_id,
                total_price=calculated_total,
                shipping_address=shipping_address,
                payment_method=payment_method,
                status='pending'
            )
            
            db.session.add(order)
            db.session.flush()  # Получаем ID заказа
            
            # Создаем элементы заказа
            for item_data in order_items:
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=item_data['product_id'],
                    product_name=item_data['product_name'],
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    total_price=item_data['total_price']
                )
                db.session.add(order_item)
            
            # Обновляем остатки товаров
            for update in product_updates:
                update['product'].stock -= update['quantity']
                db.session.add(update['product'])
            
            # Фиксируем транзакцию
            db.session.commit()
            
            # Подготавливаем ответ
            order_response = {
                'order_id': order.id,
                'order_number': order.order_number,
                'total_price': float(order.total_price),
                'status': order.status,
                'created_at': order.created_at.isoformat(),
                'items': [
                    {
                        'product_id': item.product_id,
                        'product_name': item.product_name,
                        'quantity': item.quantity,
                        'unit_price': float(item.unit_price),
                        'total_price': float(item.total_price)
                    } for item in order.items
                ]
            }
            
            return jsonify({
                'success': True,
                'message': 'Order created successfully',
                'order': order_response
            }), 201
            
        except Exception as e:
            db.session.rollback()
            raise e
            
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Error in checkout: {str(e)}')
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

def generate_order_number():
    """
    Генерация уникального номера заказа
    """
    timestamp = datetime.now().strftime('%Y%m%d')
    unique_id = str(uuid.uuid4().hex)[:8].upper()
    return f'ORD-{timestamp}-{unique_id}'

# Вспомогательный эндпоинт для получения информации о товарах в корзине
@app.route('/cart/validate', methods=['POST'])
def validate_cart():
    """
    Валидация корзины перед оформлением заказа
    """
    try:
        data = request.get_json()
        
        if not data or 'items' not in data:
            return jsonify({
                'success': False,
                'error': 'Items list is required'
            }), 400
        
        items = data['items']
        validated_items = []
        total_price = Decimal('0.00')
        
        for item in items:
            product_id = item.get('product_id')
            quantity = item.get('quantity')
            
            if not product_id or not quantity:
                continue
            
            product = Product.query.get(product_id)
            if not product:
                continue
            
            if quantity <= 0 or product.stock < quantity:
                continue
            
            item_total = Decimal(str(product.price)) * quantity
            total_price += item_total
            
            validated_items.append({
                'product_id': product.id,
                'name': product.name,
                'price': float(product.price),
                'quantity': quantity,
                'item_total': float(item_total),
                'available': True,
                'stock': product.stock
            })
        
        return jsonify({
            'success': True,
            'valid_items': validated_items,
            'total_price': float(total_price),
            'valid_items_count': len(validated_items)
        }), 200
        
    except Exception as e:
        app.logger.error(f'Error in validate_cart: {str(e)}')
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Инициализация базы данных
def init_db():
    with app.app_context():
        db.create_all()
        # Создаем тестовые товары если база пуста
        if not Product.query.first():
            products = [
                Product(name='Laptop', price=999.99, stock=10, sku='LT-001'),
                Product(name='Mouse', price=29.99, stock=50, sku='MS-002'),
                Product(name='Keyboard', price=79.99, stock=30, sku='KB-003'),
                Product(name='Monitor', price=299.99, stock=15, sku='MN-004'),
            ]
            for product in products:
                db.session.add(product)
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=False)