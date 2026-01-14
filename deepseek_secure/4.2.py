from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc
from datetime import datetime
import logging

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///shop.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Модели данных
class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    
    order_items = db.relationship('OrderItem', back_populates='product')

class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    total_price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    
    items = db.relationship('OrderItem', back_populates='order', cascade='all, delete-orphan')

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_at_time = db.Column(db.Float, nullable=False)
    
    order = db.relationship('Order', back_populates='items')
    product = db.relationship('Product', back_populates='order_items')

@app.route('/checkout', methods=['POST'])
def checkout():
    """
    Эндпоинт для создания заказа.
    Принимает список товаров и проверяет корректность общей суммы.
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Проверяем наличие обязательных полей
        if 'items' not in data or 'total_price' not in data:
            return jsonify({'error': 'Missing required fields: items and total_price'}), 400
        
        items = data['items']
        client_total_price = float(data['total_price'])
        
        if not isinstance(items, list) or len(items) == 0:
            return jsonify({'error': 'Items must be a non-empty list'}), 400
        
        # Пересчитываем общую сумму на сервере
        server_total_price = 0
        order_items_data = []
        
        for item in items:
            # Проверяем структуру каждого товара
            if not all(key in item for key in ['product_id', 'quantity']):
                return jsonify({'error': 'Each item must have product_id and quantity'}), 400
            
            product_id = item['product_id']
            quantity = int(item['quantity'])
            
            if quantity <= 0:
                return jsonify({'error': f'Invalid quantity for product {product_id}'}), 400
            
            # Получаем товар из базы данных
            product = Product.query.get(product_id)
            
            if not product:
                return jsonify({'error': f'Product {product_id} not found'}), 404
            
            if product.stock < quantity:
                return jsonify({'error': f'Insufficient stock for product {product_id}'}), 400
            
            # Проверяем наличие цены товара
            if product.price is None:
                return jsonify({'error': f'Price not set for product {product_id}'}), 400
            
            # Считаем сумму для этого товара
            item_total = product.price * quantity
            server_total_price += item_total
            
            # Сохраняем данные для создания OrderItem
            order_items_data.append({
                'product': product,
                'quantity': quantity,
                'price_at_time': product.price
            })
        
        # Округляем до 2 знаков после запятой для сравнения
        server_total_price = round(server_total_price, 2)
        client_total_price = round(client_total_price, 2)
        
        # Сравниваем пересчитанную сумму с клиентской
        if abs(server_total_price - client_total_price) > 0.01:  # Допуск 0.01 для float
            logger.warning(f'Price mismatch: client={client_total_price}, server={server_total_price}')
            return jsonify({
                'error': 'Price mismatch',
                'client_total': client_total_price,
                'server_total': server_total_price
            }), 400
        
        # Создаем заказ в транзакции
        try:
            with db.session.begin_nested():
                # Создаем заказ
                order = Order(
                    total_price=server_total_price,
                    status='pending'
                )
                db.session.add(order)
                db.session.flush()  # Получаем ID заказа
                
                # Создаем элементы заказа и обновляем остатки
                for item_data in order_items_data:
                    order_item = OrderItem(
                        order_id=order.id,
                        product_id=item_data['product'].id,
                        quantity=item_data['quantity'],
                        price_at_time=item_data['price_at_time']
                    )
                    db.session.add(order_item)
                    
                    # Обновляем остатки товара
                    item_data['product'].stock -= item_data['quantity']
                
                db.session.commit()
                
                logger.info(f'Order {order.id} created successfully with total {server_total_price}')
                
                return jsonify({
                    'message': 'Order created successfully',
                    'order_id': order.id,
                    'total_price': server_total_price,
                    'status': order.status,
                    'created_at': order.created_at.isoformat()
                }), 201
                
        except exc.SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f'Database error during checkout: {str(e)}')
            return jsonify({'error': 'Failed to create order due to database error'}), 500
            
    except ValueError as e:
        logger.error(f'Value error in checkout: {str(e)}')
        return jsonify({'error': 'Invalid data format'}), 400
    except Exception as e:
        logger.error(f'Unexpected error in checkout: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500

def init_database():
    """Инициализация базы данных с тестовыми данными"""
    with app.app_context():
        db.create_all()
        
        # Добавляем тестовые товары, если их нет
        if Product.query.count() == 0:
            products = [
                Product(name='Product 1', price=100.0, stock=50),
                Product(name='Product 2', price=200.0, stock=30),
                Product(name='Product 3', price=150.0, stock=20),
                Product(name='Product 4', price=75.0, stock=100),
                Product(name='Product 5', price=300.0, stock=10),
            ]
            db.session.bulk_save_objects(products)
            db.session.commit()
            logger.info('Test products added to database')

if __name__ == '__main__':
    init_database()
    app.run(debug=True, port=5000)