from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import secrets
import hashlib
import json

# Инициализация приложения
app = FastAPI(title="Auth Service", version="1.0.0")

# Модели данных
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Логин пользователя")
    password: str = Field(..., min_length=6, max_length=100, description="Пароль пользователя")

class SessionData(BaseModel):
    user_id: int
    username: str
    created_at: datetime
    expires_at: datetime

# Имитация базы данных пользователей (в реальном проекте заменить на настоящую БД)
fake_users_db = {
    "user1": {
        "id": 1,
        "username": "user1",
        "hashed_password": hashlib.sha256("password123".encode()).hexdigest(),
        "email": "user1@example.com",
        "is_active": True
    },
    "user2": {
        "id": 2,
        "username": "user2",
        "hashed_password": hashlib.sha256("securepass456".encode()).hexdigest(),
        "email": "user2@example.com",
        "is_active": True
    }
}

# Хранилище сессий в памяти (в реальном проекте использовать Redis или БД)
sessions_storage: Dict[str, SessionData] = {}

# Настройки сессии
SESSION_TOKEN_LENGTH = 32
SESSION_DURATION_HOURS = 24

security = HTTPBearer()

def hash_password(password: str) -> str:
    """Хеширование пароля"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля"""
    return hash_password(plain_password) == hashed_password

def create_session_token() -> str:
    """Создание уникального токена сессии"""
    return secrets.token_hex(SESSION_TOKEN_LENGTH)

def create_session(user_data: Dict[str, Any]) -> Dict[str, Any]:
    """Создание новой сессии"""
    session_token = create_session_token()
    now = datetime.now()
    expires_at = now + timedelta(hours=SESSION_DURATION_HOURS)
    
    session_data = SessionData(
        user_id=user_data["id"],
        username=user_data["username"],
        created_at=now,
        expires_at=expires_at
    )
    
    # Сохраняем сессию в хранилище
    sessions_storage[session_token] = session_data
    
    return {
        "session_token": session_token,
        "user": {
            "id": user_data["id"],
            "username": user_data["username"],
            "email": user_data["email"]
        },
        "expires_at": expires_at.isoformat(),
        "session_duration_hours": SESSION_DURATION_HOURS
    }

def cleanup_expired_sessions():
    """Очистка просроченных сессий"""
    current_time = datetime.now()
    expired_tokens = [
        token for token, session in sessions_storage.items()
        if session.expires_at < current_time
    ]
    for token in expired_tokens:
        del sessions_storage[token]

@app.post("/login", status_code=status.HTTP_200_OK)
async def login(login_data: LoginRequest) -> JSONResponse:
    """
    Эндпоинт для входа в систему
    
    Принимает логин и пароль, проверяет учетные данные
    и создает сессию при успешной аутентификации
    """
    try:
        # Очищаем просроченные сессии перед обработкой
        cleanup_expired_sessions()
        
        # Проверяем наличие пользователя
        user_data = fake_users_db.get(login_data.username)
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя или пароль"
            )
        
        # Проверяем активность аккаунта
        if not user_data.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Аккаунт заблокирован"
            )
        
        # Проверяем пароль
        if not verify_password(login_data.password, user_data["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя или пароль"
            )
        
        # Создаем сессию
        session_info = create_session(user_data)
        
        # Формируем успешный ответ
        response_data = {
            "status": "success",
            "message": "Аутентификация успешна",
            "data": session_info
        }
        
        # Создаем JSONResponse с куки (опционально)
        response = JSONResponse(content=response_data)
        
        # Устанавливаем HTTP-only куки с токеном сессии
        response.set_cookie(
            key="session_token",
            value=session_info["session_token"],
            httponly=True,
            secure=True,  # В production установить True
            samesite="strict",
            max_age=SESSION_DURATION_HOURS * 3600,
            expires=session_info["data"]["expires_at"] if isinstance(session_info, dict) and "data" in session_info else None
        )
        
        return response
        
    except HTTPException:
        # Перевыбрасываем HTTP исключения
        raise
    except Exception as e:
        # Логируем внутренние ошибки
        print(f"Ошибка при входе: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )

# Дополнительный эндпоинт для проверки сессии
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> SessionData:
    """Зависимость для получения текущего пользователя из сессии"""
    session_token = credentials.credentials
    
    # Проверяем наличие сессии
    session_data = sessions_storage.get(session_token)
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия недействительна или истекла"
        )
    
    # Проверяем срок действия
    if session_data.expires_at < datetime.now():
        # Удаляем просроченную сессию
        del sessions_storage[session_token]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла"
        )
    
    return session_data

@app.get("/verify-session")
async def verify_session(current_user: SessionData = Depends(get_current_user)):
    """Проверка валидности сессии"""
    return {
        "status": "success",
        "message": "Сессия активна",
        "user": {
            "id": current_user.user_id,
            "username": current_user.username
        },
        "expires_at": current_user.expires_at.isoformat()
    }

@app.post("/logout")
async def logout(request: Request, current_user: SessionData = Depends(get_current_user)):
    """Выход из системы (удаление сессии)"""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        session_token = auth_header.replace("Bearer ", "")
        if session_token in sessions_storage:
            del sessions_storage[session_token]
    
    response = JSONResponse(content={"status": "success", "message": "Выход выполнен успешно"})
    response.delete_cookie(key="session_token")
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)