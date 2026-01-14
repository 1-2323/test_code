from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import uuid
import os
from decimal import Decimal
import hashlib

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///tests.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Модель теста
class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    passing_score = db.Column(db.Numeric(5, 2), nullable=False, default=70.00)  # Проходной балл в процентах
    max_score = db.Column(db.Integer, nullable=False, default=100)  # Максимальный балл
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    time_limit_minutes = db.Column(db.Integer, default=60)  # Ограничение по времени

# Модель попытки прохождения теста
class TestAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('test.id'), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)  # ID пользователя из системы аутентификации
    session_id = db.Column(db.String(100), nullable=False)  # Уникальный идентификатор сессии
    score = db.Column(db.Numeric(5, 2), nullable=False)  # Набранные баллы
    percentage = db.Column(db.Numeric(5, 2), nullable=False)  # Процент правильных ответов
    passed = db.Column(db.Boolean, nullable=False)
    started_at = db.Column(db.DateTime, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    
    # Связь с Test и Certificate
    test = db.relationship('Test')
    certificate = db.relationship('Certificate', uselist=False, backref='test_attempt')

# Модель сертификата
class Certificate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('test_attempt.id'), unique=True, nullable=False)
    certificate_number = db.Column(db.String(100), unique=True, nullable=False)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    download_url = db.Column(db.String(500))
    verification_hash = db.Column(db.String(64), unique=True, nullable=False)  # SHA-256 для верификации
    is_revoked = db.Column(db.Boolean, default=False)
    
    # Дополнительные поля для сертификата
    recipient_name = db.Column(db.String(200))
    test_name = db.Column(db.String(200))
    score = db.Column(db.Numeric(5, 2))
    percentage = db.Column(db.Numeric(5, 2))

@app.route('/test/submit', methods=['POST'])
def submit_test():
    """
    Эндпоинт для отправки результатов теста и выдачи сертификата
    """
    try:
        # В реальном приложении здесь должна быть аутентификация
        # user_id = get_current_user_id()
        # user_name = get_current_user_name()
        
        data = request.get_json()
        
        # Валидация входных данных
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        test_id = data.get('test_id')
        score = data.get('score')
        session_id = data.get('session_id')
        started_at = data.get('started_at')
        
        if not all([test_id, score, session_id, started_at]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: test_id, score, session_id, started_at'
            }), 400
        
        # Проверка существования теста
        test = Test.query.filter_by(id=test_id, is_active=True).first()
        if not test:
            return jsonify({
                'success': False,
                'error': 'Test not found or inactive'
            }), 404
        
        # Проверка диапазона баллов
        try:
            score_decimal = Decimal(str(score))
            if score_decimal < 0 or score_decimal > test.max_score:
                return jsonify({
                    'success': False,
                    'error': f'Score must be between 0 and {test.max_score}'
                }), 400
        except:
            return jsonify({
                'success': False,
                'error': 'Invalid score format'
            }), 400
        
        # Проверка времени начала теста
        try:
            started_at_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
        except:
            return jsonify({
                'success': False,
                'error': 'Invalid started_at format. Use ISO 8601'
            }), 400
        
        # Проверка времени прохождения теста
        time_elapsed = datetime.utcnow() - started_at_dt
        if time_elapsed > timedelta(minutes=test.time_limit_minutes + 5):  # +5 минут на задержку сети
            return jsonify({
                'success': False,
                'error': 'Test submission timeout'
            }), 408
        
        # Проверка существующей попытки с таким session_id
        existing_attempt = TestAttempt.query.filter_by(
            session_id=session_id,
            test_id=test_id
        ).first()
        
        if existing_attempt:
            return jsonify({
                'success': False,
                'error': 'Test already submitted'
            }), 409
        
        # Расчет процента
        percentage = (score_decimal / Decimal(str(test.max_score))) * Decimal('100')
        percentage_rounded = round(percentage, 2)
        
        # Проверка проходного порога
        passed = percentage_rounded >= test.passing_score
        
        # Заглушки для демонстрации (в реальном приложении должны браться из аутентификации)
        user_id = 1
        user_name = "John Doe"
        
        # Создаем попытку теста
        attempt = TestAttempt(
            test_id=test_id,
            user_id=user_id,
            session_id=session_id,
            score=score_decimal,
            percentage=percentage_rounded,
            passed=passed,
            started_at=started_at_dt,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        
        db.session.add(attempt)
        db.session.flush()  # Получаем ID попытки
        
        certificate_data = None
        
        # Если тест пройден успешно, создаем сертификат
        if passed:
            certificate = create_certificate(attempt, test, user_name)
            db.session.add(certificate)
            
            certificate_data = {
                'certificate_number': certificate.certificate_number,
                'issued_at': certificate.issued_at.isoformat(),
                'expires_at': certificate.expires_at.isoformat() if certificate.expires_at else None,
                'download_url': certificate.download_url,
                'verification_url': f'/certificate/verify/{certificate.verification_hash}',
                'test_name': test.name,
                'score': float(attempt.score),
                'percentage': float(attempt.percentage),
                'passing_score': float(test.passing_score)
            }
        
        db.session.commit()
        
        # Формируем ответ
        response_data = {
            'attempt_id': attempt.id,
            'test_id': test.id,
            'test_name': test.name,
            'score': float(attempt.score),
            'max_score': test.max_score,
            'percentage': float(attempt.percentage),
            'passing_score': float(test.passing_score),
            'passed': attempt.passed,
            'submitted_at': attempt.submitted_at.isoformat(),
            'time_spent_seconds': int(time_elapsed.total_seconds()),
            'time_limit_minutes': test.time_limit_minutes
        }
        
        if certificate_data:
            response_data['certificate'] = certificate_data
        
        return jsonify({
            'success': True,
            'message': 'Test submitted successfully',
            'data': response_data
        }), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Error in submit_test: {str(e)}')
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

def create_certificate(attempt, test, recipient_name):
    """
    Создание сертификата для успешной попытки теста
    """
    # Генерация уникального номера сертификата
    certificate_number = generate_certificate_number()
    
    # Генерация хеша для верификации
    verification_data = f"{attempt.id}{test.id}{recipient_name}{datetime.utcnow().isoformat()}{uuid.uuid4().hex}"
    verification_hash = hashlib.sha256(verification_data.encode()).hexdigest()
    
    # Расчет даты истечения (например, через 1 год)
    expires_at = datetime.utcnow() + timedelta(days=365)
    
    # Генерация URL для скачивания (в реальном приложении должен генерироваться PDF)
    download_url = f"/certificates/download/{certificate_number}"
    
    certificate = Certificate(
        attempt_id=attempt.id,
        certificate_number=certificate_number,
        expires_at=expires_at,
        download_url=download_url,
        verification_hash=verification_hash,
        recipient_name=recipient_name,
        test_name=test.name,
        score=attempt.score,
        percentage=attempt.percentage
    )
    
    return certificate

def generate_certificate_number():
    """
    Генерация уникального номера сертификата
    """
    timestamp = datetime.now().strftime('%Y%m%d')
    unique_id = str(uuid.uuid4().hex)[:12].upper()
    return f'CERT-{timestamp}-{unique_id}'

# Эндпоинт для проверки сертификата
@app.route('/certificate/verify/<verification_hash>', methods=['GET'])
def verify_certificate(verification_hash):
    """
    Верификация сертификата по хешу
    """
    try:
        certificate = Certificate.query.filter_by(
            verification_hash=verification_hash,
            is_revoked=False
        ).first()
        
        if not certificate:
            return jsonify({
                'success': False,
                'error': 'Certificate not found or revoked'
            }), 404
        
        # Проверка срока действия
        is_expired = certificate.expires_at and certificate.expires_at < datetime.utcnow()
        
        # Получаем информацию о попытке теста
        attempt = TestAttempt.query.get(certificate.attempt_id)
        
        response_data = {
            'certificate_number': certificate.certificate_number,
            'recipient_name': certificate.recipient_name,
            'test_name': certificate.test_name,
            'score': float(certificate.score),
            'percentage': float(certificate.percentage),
            'issued_at': certificate.issued_at.isoformat(),
            'expires_at': certificate.expires_at.isoformat() if certificate.expires_at else None,
            'is_valid': not is_expired and not certificate.is_revoked,
            'is_expired': is_expired,
            'is_revoked': certificate.is_revoked,
            'verification_hash': certificate.verification_hash
        }
        
        if attempt:
            response_data['submitted_at'] = attempt.submitted_at.isoformat()
            response_data['test_id'] = attempt.test_id
        
        return jsonify({
            'success': True,
            'certificate': response_data
        }), 200
        
    except Exception as e:
        app.logger.error(f'Error in verify_certificate: {str(e)}')
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Эндпоинт для начала теста
@app.route('/test/start', methods=['POST'])
def start_test():
    """
    Начало прохождения теста, создание сессии
    """
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        
        if not test_id:
            return jsonify({
                'success': False,
                'error': 'test_id is required'
            }), 400
        
        test = Test.query.filter_by(id=test_id, is_active=True).first()
        if not test:
            return jsonify({
                'success': False,
                'error': 'Test not found or inactive'
            }), 404
        
        # Генерация уникальной сессии
        session_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        
        # В реальном приложении здесь должен быть user_id из аутентификации
        user_id = 1
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'started_at': started_at.isoformat(),
            'test_name': test.name,
            'time_limit_minutes': test.time_limit_minutes,
            'max_score': test.max_score,
            'passing_score': float(test.passing_score)
        }), 200
        
    except Exception as e:
        app.logger.error(f'Error in start_test: {str(e)}')
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Инициализация базы данных
def init_db():
    with app.app_context():
        db.create_all()
        # Создаем тестовый тест если база пуста
        if not Test.query.first():
            test = Test(
                name='Python Programming Basics',
                description='Test your knowledge of Python programming fundamentals',
                passing_score=75.00,
                max_score=100,
                time_limit_minutes=45
            )
            db.session.add(test)
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=False)