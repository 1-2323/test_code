from typing import Optional, Dict, Any, Callable
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import secrets
import time
import json
import hashlib

# Конфигурация сессий
SESSION_CONFIG = {
    'cookie_name': 'session_id',
    'session_ttl': 3600,  # 1 час в секундах
    'cookie_secure': False,  # В production установить True
    'cookie_http_only': True,
    'cookie_samesite': 'lax',
    'cookie_path': '/',
    'cookie_domain': None,  # Можно указать конкретный домен
    'secret_key': 'your-secret-key-change-in-production',  # Изменить в production!
    'session_storage': 'memory'  # memory или redis (в production использовать redis)
}

# Хранилище сессий в памяти
memory_sessions: Dict[str, Dict[str, Any]] = {}

class SessionManager:
    """Менеджер сессий"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    def generate_session_id(self) -> str:
        """Генерация уникального идентификатора сессии"""
        return secrets.token_urlsafe(32)
    
    def create_session_data(self) -> Dict[str, Any]:
        """Создание базовой структуры данных сессии"""
        now = time.time()
        return {
            'created_at': now,
            'last_accessed': now,
            'expires_at': now + self.config['session_ttl'],
            'data': {},
            'user_agent': '',
            'ip_address': ''
        }
    
    def sign_session_id(self, session_id: str) -> str:
        """Подпись идентификатора сессии для предотвращения подделки"""
        signature = hashlib.sha256(
            f"{session_id}{self.config['secret_key']}".encode()
        ).hexdigest()[:16]
        return f"{session_id}.{signature}"
    
    def verify_session_id(self, signed_session_id: str) -> Optional[str]:
        """Проверка подписи идентификатора сессии"""
        if '.' not in signed_session_id:
            return None
        
        session_id, signature = signed_session_id.rsplit('.', 1)
        
        expected_signature = hashlib.sha256(
            f"{session_id}{self.config['secret_key']}".encode()
        ).hexdigest()[:16]
        
        if secrets.compare_digest(signature, expected_signature):
            return session_id
        return None
    
    def get_session_storage(self):
        """Получение хранилища сессий"""
        if self.config['session_storage'] == 'redis':
            # В реальном проекте реализовать подключение к Redis
            raise NotImplementedError("Redis storage not implemented")
        return memory_sessions
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Получение данных сессии по ID"""
        storage = self.get_session_storage()
        
        if session_id not in storage:
            return None
        
        session_data = storage[session_id]
        
        # Проверяем, не истекла ли сессия
        if time.time() > session_data['expires_at']:
            self.delete_session(session_id)
            return None
        
        # Обновляем время последнего доступа
        session_data['last_accessed'] = time.time()
        storage[session_id] = session_data
        
        return session_data
    
    def create_session(self, session_id: Optional[str] = None) -> str:
        """Создание новой сессии"""
        if not session_id:
            session_id = self.generate_session_id()
        
        session_data = self.create_session_data()
        storage = self.get_session_storage()
        storage[session_id] = session_data
        
        return session_id
    
    def update_session(self, session_id: str, updates: Dict[str, Any]):
        """Обновление данных сессии"""
        storage = self.get_session_storage()
        
        if session_id in storage:
            session_data = storage[session_id]
            # Обновляем только данные, не метаинформацию
            if 'data' in updates:
                session_data['data'].update(updates['data'])
            else:
                session_data.update(updates)
            
            storage[session_id] = session_data
    
    def delete_session(self, session_id: str):
        """Удаление сессии"""
        storage = self.get_session_storage()
        if session_id in storage:
            del storage[session_id]
    
    def cleanup_expired_sessions(self):
        """Очистка просроченных сессий"""
        storage = self.get_session_storage()
        current_time = time.time()
        
        expired_keys = [
            key for key, session in storage.items()
            if session['expires_at'] < current_time
        ]
        
        for key in expired_keys:
            del storage[key]

# Инициализация менеджера сессий
session_manager = SessionManager(SESSION_CONFIG)

class SessionMiddleware:
    """Middleware для управления сессиями через cookies"""
    
    def __init__(self, app, session_manager: SessionManager):
        self.app = app
        self.session_manager = session_manager
        self.cookie_name = session_manager.config['cookie_name']
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        
        request = Request(scope, receive)
        response = await self.handle_request(request)
        
        if response is None:
            return await self.app(scope, receive, send)
        
        await response(scope, receive, send)
    
    async def handle_request(self, request: Request) -> Optional[Response]:
        """Обработка входящего запроса"""
        
        # Очищаем просроченные сессии (можно делать реже, например раз в 10 минут)
        if int(time.time()) % 600 == 0:  # Пример: каждые 10 минут
            self.session_manager.cleanup_expired_sessions()
        
        # Извлекаем session_id из cookie
        session_id = None
        signed_session_id = request.cookies.get(self.cookie_name)
        
        if signed_session_id:
            session_id = self.session_manager.verify_session_id(signed_session_id)
        
        # Получаем или создаем сессию
        session_data = None
        if session_id:
            session_data = self.session_manager.get_session(session_id)
        
        if not session_data:
            # Создаем новую сессию
            session_id = self.session_manager.create_session()
            session_data = self.session_manager.get_session(session_id)
            
            # Добавляем информацию о клиенте
            if session_data:
                session_data['user_agent'] = request.headers.get('user-agent', '')
                session_data['ip_address'] = request.client.host if request.client else ''
                self.session_manager.update_session(session_id, session_data)
        
        # Добавляем объект сессии в request.state
        request.state.session_id = session_id
        request.state.session_data = session_data['data'] if session_data else {}
        request.state.session_manager = self.session_manager
        
        # Обрабатываем запрос
        response = await self.call_next_with_session(request, session_id)
        
        return response
    
    async def call_next_with_session(self, request: Request, session_id: str) -> Response:
        """Вызов следующего middleware/обработчика с обновлением сессии"""
        
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Добавляем cookie с сессией в ответ
                headers = dict(message.get("headers", []))
                
                # Подписываем session_id для безопасности
                signed_session_id = self.session_manager.sign_session_id(session_id)
                
                # Строим cookie строку
                cookie_parts = [
                    f"{self.cookie_name}={signed_session_id}",
                    f"Max-Age={self.session_manager.config['session_ttl']}",
                    f"Path={self.session_manager.config['cookie_path']}"
                ]
                
                if self.session_manager.config['cookie_http_only']:
                    cookie_parts.append("HttpOnly")
                
                if self.session_manager.config['cookie_secure']:
                    cookie_parts.append("Secure")
                
                if self.session_manager.config['cookie_samesite']:
                    cookie_parts.append(f"SameSite={self.session_manager.config['cookie_samesite']}")
                
                if self.session_manager.config['cookie_domain']:
                    cookie_parts.append(f"Domain={self.session_manager.config['cookie_domain']}")
                
                headers[b"set-cookie"] = "; ".join(cookie_parts).encode()
                message["headers"] = list(headers.items())
            
            await send(message)
        
        # Создаем новый send для обертки
        original_send = None
        
        async def receive_wrapper():
            nonlocal original_send
            if original_send is None:
                original_send = send
        
        # Вызываем следующее приложение
        response = await self.app(request.scope, request.receive, send_wrapper)
        return response

# Декораторы и утилиты для работы с сессиями
def get_session(request: Request) -> Dict[str, Any]:
    """Получение данных сессии из запроса"""
    return getattr(request.state, 'session_data', {})

def set_session_data(request: Request, key: str, value: Any):
    """Установка значения в сессии"""
    session_id = getattr(request.state, 'session_id', None)
    session_manager = getattr(request.state, 'session_manager', None)
    
    if session_id and session_manager:
        current_data = get_session(request)
        current_data[key] = value
        session_manager.update_session(session_id, {'data': current_data})
        request.state.session_data = current_data

def delete_session_data(request: Request, key: str):
    """Удаление значения из сессии"""
    session_id = getattr(request.state, 'session_id', None)
    session_manager = getattr(request.state, 'session_manager', None)
    
    if session_id and session_manager:
        current_data = get_session(request)
        if key in current_data:
            del current_data[key]
            session_manager.update_session(session_id, {'data': current_data})
            request.state.session_data = current_data

def clear_session(request: Request):
    """Полная очистка данных сессии"""
    session_id = getattr(request.state, 'session_id', None)
    session_manager = getattr(request.state, 'session_manager', None)
    
    if session_id and session_manager:
        session_manager.update_session(session_id, {'data': {}})
        request.state.session_data = {}

def destroy_session(request: Request, response: Response):
    """Уничтожение сессии (выход пользователя)"""
    session_id = getattr(request.state, 'session_id', None)
    session_manager = getattr(request.state, 'session_manager', None)
    
    if session_id and session_manager:
        session_manager.delete_session(session_id)
    
    # Удаляем cookie
    response.delete_cookie(
        key=SESSION_CONFIG['cookie_name'],
        path=SESSION_CONFIG['cookie_path'],
        domain=SESSION_CONFIG['cookie_domain']
    )

# Пример использования в FastAPI приложении
app = FastAPI()

# Подключаем middleware
app.add_middleware(SessionMiddleware, session_manager=session_manager)

# Пример роута, использующего сессию
@app.get("/session-info")
async def session_info(request: Request):
    """Получение информации о текущей сессии"""
    session_data = get_session(request)
    session_id = getattr(request.state, 'session_id', None)
    
    return {
        "session_id": session_id,
        "session_data": session_data,
        "session_keys": list(session_data.keys())
    }

@app.post("/session/set")
async def set_session_value(request: Request, key: str, value: str):
    """Установка значения в сессии"""
    set_session_data(request, key, value)
    return {"status": "success", "message": f"Значение '{key}' установлено"}

@app.delete("/session/remove")
async def remove_session_value(request: Request, key: str):
    """Удаление значения из сессии"""
    delete_session_data(request, key)
    return {"status": "success", "message": f"Значение '{key}' удалено"}

@app.post("/session/clear")
async def clear_session_data(request: Request):
    """Очистка всех данных сессии"""
    clear_session(request)
    return {"status": "success", "message": "Сессия очищена"}

@app.post("/logout")
async def logout(request: Request, response: Response):
    """Выход из системы с уничтожением сессии"""
    destroy_session(request, response)
    return {"status": "success", "message": "Выход выполнен успешно"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)