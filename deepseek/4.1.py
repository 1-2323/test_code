from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    secret_question = db.Column(db.String(300), nullable=False)
    secret_answer_hash = db.Column(db.String(256), nullable=False)
    recovery_token = db.Column(db.String(100))
    token_expiry = db.Column(db.DateTime)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def set_secret_answer(self, answer):
        self.secret_answer_hash = generate_password_hash(answer.lower().strip())
    
    def check_secret_answer(self, answer):
        return check_password_hash(self.secret_answer_hash, answer.lower().strip())

# Модель для хранения запросов на восстановление
class RecoveryAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ip_address = db.Column(db.String(45))
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)
    successful = db.Column(db.Boolean, default=False)

@app.route('/recover', methods=['POST'])
def recover_password():
    """
    Эндпоинт для восстановления пароля через секретный вопрос
    """
    try:
        data = request.get_json()
        
        # Валидация входных данных
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        email = data.get('email')
        secret_answer = data.get('secret_answer')
        new_password = data.get('new_password')
        
        if not all([email, secret_answer, new_password]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: email, secret_answer, new_password'
            }), 400
        
        if len(new_password) < 8:
            return jsonify({
                'success': False,
                'error': 'New password must be at least 8 characters long'
            }), 400
        
        # Поиск пользователя
        user = User.query.filter_by(email=email).first()
        if not user:
            # Возвращаем общий ответ для безопасности
            return jsonify({
                'success': False,
                'error': 'Invalid credentials'
            }), 401
        
        # Проверка секретного ответа
        if not user.check_secret_answer(secret_answer):
            # Логируем неудачную попытку
            attempt = RecoveryAttempt(
                user_id=user.id,
                ip_address=request.remote_addr,
                successful=False
            )
            db.session.add(attempt)
            db.session.commit()
            
            return jsonify({
                'success': False,
                'error': 'Invalid credentials'
            }), 401
        
        # Проверка частоты запросов (дополнительная защита)
        recent_attempts = RecoveryAttempt.query.filter(
            RecoveryAttempt.user_id == user.id,
            RecoveryAttempt.attempted_at > datetime.utcnow() - timedelta(minutes=15)
        ).count()
        
        if recent_attempts > 5:
            return jsonify({
                'success': False,
                'error': 'Too many attempts. Please try again later.'
            }), 429
        
        # Обновление пароля
        user.set_password(new_password)
        
        # Генерация нового токена восстановления (если используется)
        user.recovery_token = str(uuid.uuid4())
        user.token_expiry = datetime.utcnow() + timedelta(hours=24)
        
        # Логируем успешную попытку
        attempt = RecoveryAttempt(
            user_id=user.id,
            ip_address=request.remote_addr,
            successful=True
        )
        db.session.add(attempt)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Password has been successfully reset'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Error in recover_password: {str(e)}')
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Дополнительный эндпоинт для проверки существования пользователя и получения вопроса
@app.route('/recover/check', methods=['POST'])
def check_user_for_recovery():
    """
    Проверка существования пользователя и возврат секретного вопроса
    """
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({
                'success': False,
                'error': 'Email is required'
            }), 400
        
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({
                'success': False,
                'error': 'User not found'
            }), 404
        
        return jsonify({
            'success': True,
            'secret_question': user.secret_question,
            'message': 'User found'
        }), 200
        
    except Exception as e:
        app.logger.error(f'Error in check_user_for_recovery: {str(e)}')
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Инициализация базы данных
def init_db():
    with app.app_context():
        db.create_all()
        # Создадим тестового пользователя если база пуста
        if not User.query.first():
            test_user = User(
                email='test@example.com',
                secret_question='What is your favorite book?'
            )
            test_user.set_password('defaultPassword123')
            test_user.set_secret_answer('Harry Potter')
            db.session.add(test_user)
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=False)