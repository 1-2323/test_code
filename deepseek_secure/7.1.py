import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from flask import Flask, request, jsonify, make_response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import redis

app = Flask(__name__)

# Конфигурация Redis для хранения сессий и счетчиков неудачных попыток
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# Конфигурация ограничения попыток входа
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = 900  # 15 минут в секундах
FAILED_ATTEMPTS_KEY_PREFIX = 'failed_attempts:'
LOCKOUT_KEY_PREFIX = 'lockout:'

# Конфигурация сессий
SESSION_DURATION = timedelta(hours=24)
SESSION_KEY_PREFIX = 'session:'
SESSION_ID_LENGTH = 32

# Инициализация Flask-Limiter для глобального rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour", "10 per minute"]
)

class AuthService:
    """Сервис аутентификации"""
    
    @staticmethod
    def verify_credentials(username: str, password: str) -> bool:
        """
        Проверка логина и пароля.
        В реальном приложении здесь должно быть обращение к БД.
        """
        # Хэширование пароля для сравнения (в реальном приложении используйте bcrypt/scrypt)
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        # Пример проверки (в реальном приложении замените на запрос к БД)
        # Здесь должен быть код для получения хэша пароля пользователя из БД
        stored_hash = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"  # 'password'
        
        # Временная заглушка для демонстрации
        correct_username = "test_user"
        correct_password_hash = stored_hash
        
        return username == correct_username and hashed_password == correct_password_hash
    
    @staticmethod
    def is_account_locked(username: str) -> Tuple[bool, Optional[int]]:
        """
        Проверка, заблокирован ли аккаунт.
        Возвращает (заблокирован, оставшееся_время_блокировки).
        """
        lockout_key = f"{LOCKOUT_KEY_PREFIX}{username}"
        lockout_until = redis_client.get(lockout_key)
        
        if lockout_until:
            lockout_time = int(lockout_until)
            current_time = int(time.time())
            
            if current_time < lockout_time:
                remaining = lockout_time - current_time
                return True, remaining
        
        return False, None
    
    @staticmethod
    def record_failed_attempt(username: str) -> None:
        """
        Запись неудачной попытки входа и блокировка при превышении лимита.
        """
        failed_key = f"{FAILED_ATTEMPTS_KEY_PREFIX}{username}"
        
        # Увеличиваем счетчик неудачных попыток
        failed_attempts = redis_client.incr(failed_key)
        
        # Устанавливаем срок жизни ключа (сброс через 1 час после последней неудачной попытки)
        redis_client.expire(failed_key, 3600)
        
        # Если превышен лимит - блокируем аккаунт
        if failed_attempts >= MAX_FAILED_ATTEMPTS:
            lockout_key = f"{LOCKOUT_KEY_PREFIX}{username}"
            lockout_until = int(time.time()) + LOCKOUT_DURATION
            redis_client.setex(lockout_key, LOCKOUT_DURATION, lockout_until)
            
            # Сбрасываем счетчик неудачных попыток
            redis_client.delete(failed_key)
    
    @staticmethod
    def clear_failed_attempts(username: str) -> None:
        """Очистка счетчика неудачных попыток при успешном входе."""
        failed_key = f"{FAILED_ATTEMPTS_KEY_PREFIX}{username}"
        lockout_key = f"{LOCKOUT_KEY_PREFIX}{username}"
        
        redis_client.delete(failed_key)
        redis_client.delete(lockout_key)
    
    @staticmethod
    def create_session(username: str) -> Tuple[str, datetime]:
        """
        Создание новой сессии.
        Возвращает (session_id, expiry_time).
        """
        session_id = secrets.token_hex(SESSION_ID_LENGTH // 2)
        session_key = f"{SESSION_KEY_PREFIX}{session_id}"
        expiry_time = datetime.utcnow() + SESSION_DURATION
        
        session_data = {
            'username': username,
            'created_at': datetime.utcnow().isoformat(),
            'expires_at': expiry_time.isoformat()
        }
        
        # Сохраняем сессию в Redis
        redis_client.hset(session_key, mapping=session_data)
        redis_client.expireat(session_key, expiry_time)
        
        return session_id, expiry_time


@app.route('/login', methods=['POST'])
@limiter.limit("10 per minute")  # Дополнительный rate limiting на эндпоинт
def login():
    """
    Эндпоинт для входа в систему.
    Принимает JSON с полями 'username' и 'password'.
    """
    # Проверка Content-Type
    if not request.is_json:
        return jsonify({
            'success': False,
            'error': 'Content-Type must be application/json'
        }), 415
    
    data = request.get_json()
    
    # Валидация входных данных
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing username or password'
        }), 400
    
    username = data['username'].strip()
    password = data['password']
    
    # Проверка на пустые значения
    if not username or not password:
        return jsonify({
            'success': False,
            'error': 'Username and password cannot be empty'
        }), 400
    
    # Проверка блокировки аккаунта
    is_locked, remaining_time = AuthService.is_account_locked(username)
    if is_locked:
        return jsonify({
            'success': False,
            'error': f'Account is locked due to too many failed attempts',
            'lockout_remaining': remaining_time
        }), 423  # 423 Locked
    
    # Проверка учетных данных
    if AuthService.verify_credentials(username, password):
        # Очищаем счетчик неудачных попыток
        AuthService.clear_failed_attempts(username)
        
        # Создаем сессию
        session_id, expiry_time = AuthService.create_session(username)
        
        # Создаем HTTP-only cookie для сессии
        response = make_response(jsonify({
            'success': True,
            'message': 'Login successful',
            'session_expiry': expiry_time.isoformat()
        }))
        
        response.set_cookie(
            key='session_id',
            value=session_id,
            httponly=True,
            secure=True,  # В продакшене должен быть True (требует HTTPS)
            samesite='Strict',
            expires=expiry_time
        )
        
        # Дополнительный заголовок для клиента
        response.headers['X-Session-Expiry'] = expiry_time.isoformat()
        
        return response, 200
    else:
        # Записываем неудачную попытку
        AuthService.record_failed_attempt(username)
        
        # Получаем текущее количество неудачных попыток
        failed_key = f"{FAILED_ATTEMPTS_KEY_PREFIX}{username}"
        failed_attempts = int(redis_client.get(failed_key) or 0)
        attempts_left = MAX_FAILED_ATTEMPTS - failed_attempts
        
        return jsonify({
            'success': False,
            'error': 'Invalid username or password',
            'attempts_remaining': max(0, attempts_left)
        }), 401


@app.errorhandler(429)
def ratelimit_handler(e):
    """Обработчик превышения лимита запросов."""
    return jsonify({
        'success': False,
        'error': 'Rate limit exceeded',
        'message': str(e.description)
    }), 429


if __name__ == '__main__':
    # В продакшене используйте production-ready сервер (Gunicorn, uWSGI)
    app.run(debug=False, host='0.0.0.0', port=5000)