import uuid
import time
from typing import Optional, Tuple
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, g, make_response

app = Flask(__name__)

# Конфигурация сессий
SESSION_COOKIE_NAME = "session_id"
SESSION_DURATION = 3600  # 1 час в секундах
SESSION_RENEWAL_THRESHOLD = 300  # Обновлять за 5 минут до истечения

# Хранилище сессий (в реальном приложении используйте Redis, БД и т.д.)
sessions_store = {}


class Session:
    """Класс для представления сессии пользователя"""
    
    def __init__(self, session_id: str, user_id: Optional[str] = None):
        self.session_id = session_id
        self.user_id = user_id
        self.created_at = datetime.now()
        self.last_accessed = self.created_at
        self.data = {}
        self.expires_at = self.created_at + timedelta(seconds=SESSION_DURATION)
    
    def is_expired(self) -> bool:
        """Проверяет, истекла ли сессия"""
        return datetime.now() > self.expires_at
    
    def renew(self) -> None:
        """Обновляет время жизни сессии"""
        self.last_accessed = datetime.now()
        self.expires_at = self.last_accessed + timedelta(seconds=SESSION_DURATION)
    
    def should_renew(self) -> bool:
        """Проверяет, нужно ли обновлять сессию"""
        time_until_expiry = (self.expires_at - datetime.now()).total_seconds()
        return time_until_expiry < SESSION_RENEWAL_THRESHOND
    
    def get(self, key: str, default=None):
        """Получает значение из данных сессии"""
        return self.data.get(key, default)
    
    def set(self, key: str, value) -> None:
        """Устанавливает значение в данных сессии"""
        self.data[key] = value
    
    def delete(self, key: str) -> None:
        """Удаляет значение из данных сессии"""
        if key in self.data:
            del self.data[key]
    
    def clear(self) -> None:
        """Очищает все данные сессии"""
        self.data.clear()


def create_session(user_id: Optional[str] = None) -> Session:
    """Создает новую сессию"""
    session_id = str(uuid.uuid4())
    session = Session(session_id, user_id)
    sessions_store[session_id] = session
    return session


def get_session(session_id: str) -> Optional[Session]:
    """Получает сессию по идентификатору"""
    if session_id not in sessions_store:
        return None
    
    session = sessions_store[session_id]
    
    if session.is_expired():
        # Удаляем просроченную сессию
        delete_session(session_id)
        return None
    
    return session


def delete_session(session_id: str) -> None:
    """Удаляет сессию"""
    if session_id in sessions_store:
        del sessions_store[session_id]


def cleanup_expired_sessions() -> None:
    """Очищает просроченные сессии (вызывать периодически)"""
    current_time = datetime.now()
    expired_ids = [
        session_id for session_id, session in sessions_store.items()
        if session.expires_at < current_time
    ]
    
    for session_id in expired_ids:
        delete_session(session_id)


def session_middleware():
    """Middleware для управления сессиями"""
    
    @app.before_request
    def load_session():
        """Загружает сессию перед обработкой запроса"""
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session = None
        
        if session_id:
            session = get_session(session_id)
        
        if not session:
            # Создаем новую сессию, если нет валидной
            session = create_session()
        
        # Проверяем, нужно ли обновить сессию
        if session.should_renew():
            session.renew()
        
        # Сохраняем сессию в контексте приложения
        g.session = session
    
    @app.after_request
    def set_session_cookie(response):
        """Устанавливает cookie с сессией после обработки запроса"""
        if hasattr(g, 'session'):
            session = g.session
            
            # Удаляем сессию, если она истекла
            if session.is_expired():
                delete_session(session.session_id)
                response.set_cookie(
                    SESSION_COOKIE_NAME,
                    '',
                    expires=0,
                    httponly=True,
                    secure=True,
                    samesite='Strict'
                )
            else:
                # Устанавливаем cookie с защитными флагами
                response.set_cookie(
                    SESSION_COOKIE_NAME,
                    session.session_id,
                    max_age=SESSION_DURATION,
                    httponly=True,      # Защита от XSS
                    secure=True,        # Только HTTPS (в production)
                    samesite='Strict',  # Защита от CSRF
                    path='/'
                )
                
                # Обновляем время последнего доступа
                session.last_accessed = datetime.now()
        
        return response


def require_session(f):
    """Декоратор для проверки наличия валидной сессии"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'session') or g.session.is_expired():
            return make_response({"error": "Session expired or invalid"}, 401)
        return f(*args, **kwargs)
    return decorated_function


def require_authenticated(f):
    """Декоратор для проверки аутентификации пользователя"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'session') or not g.session.user_id:
            return make_response({"error": "Authentication required"}, 401)
        return f(*args, **kwargs)
    return decorated_function


# Инициализация middleware
session_middleware()


# Пример маршрутов для демонстрации
@app.route('/login', methods=['POST'])
def login():
    """Эндпоинт для входа пользователя"""
    # В реальном приложении здесь была бы проверка учетных данных
    user_id = "user_123"  # Получаем из базы данных
    
    if hasattr(g, 'session'):
        g.session.user_id = user_id
        g.session.set('login_time', datetime.now().isoformat())
    
    return {"status": "logged_in", "user_id": user_id}


@app.route('/profile')
@require_authenticated
def profile():
    """Защищенный эндпоинт, требующий аутентификации"""
    return {
        "user_id": g.session.user_id,
        "session_data": g.session.data,
        "expires_at": g.session.expires_at.isoformat()
    }


@app.route('/logout', methods=['POST'])
@require_session
def logout():
    """Эндпоинт для выхода из системы"""
    if hasattr(g, 'session'):
        session_id = g.session.session_id
        delete_session(session_id)
    
    response = make_response({"status": "logged_out"})
    response.set_cookie(
        SESSION_COOKIE_NAME,
        '',
        expires=0,
        httponly=True,
        secure=True,
        samesite='Strict'
    )
    return response


@app.route('/session-info')
@require_session
def session_info():
    """Информация о текущей сессии"""
    session = g.session
    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "created_at": session.created_at.isoformat(),
        "last_accessed": session.last_accessed.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "data": session.data
    }


if __name__ == '__main__':
    # В production установите DEBUG=False
    app.run(debug=True, ssl_context='adhoc')  # adhoc для тестирования HTTPS