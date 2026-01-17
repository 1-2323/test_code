from fastapi import FastAPI, HTTPException, Depends, status, Request
from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional, Dict, Any
from datetime import datetime
from passlib.context import CryptContext
import re
import sqlite3
from contextlib import contextmanager
from uuid import uuid4
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="User Registration Service")

# --- Pydantic модели для валидации ---
class UserRegistrationRequest(BaseModel):
    """Модель запроса на регистрацию пользователя."""
    
    email: EmailStr = Field(..., description="Email пользователя")
    password: str = Field(..., min_length=8, max_length=100, description="Пароль")
    confirm_password: str = Field(..., description="Подтверждение пароля")
    username: str = Field(..., min_length=3, max_length=50, description="Имя пользователя")
    first_name: Optional[str] = Field(None, max_length=50, description="Имя")
    last_name: Optional[str] = Field(None, max_length=50, description="Фамилия")
    
    @validator('username')
    def validate_username(cls, v):
        """Валидация имени пользователя."""
        # Только буквы, цифры, подчеркивания и точки
        if not re.match(r'^[a-zA-Z0-9_.]+$', v):
            raise ValueError('Имя пользователя может содержать только буквы, цифры, точки и подчеркивания')
        
        # Не может начинаться с точки или подчеркивания
        if v.startswith('.') or v.startswith('_'):
            raise ValueError('Имя пользователя не может начинаться с точки или подчеркивания')
        
        return v
    
    @validator('password')
    def validate_password_strength(cls, v):
        """Проверка сложности пароля."""
        errors = []
        
        # Проверка на минимальную длину уже выполняется через Field
        
        # Проверка наличия заглавных букв
        if not re.search(r'[A-Z]', v):
            errors.append('Пароль должен содержать хотя бы одну заглавную букву')
        
        # Проверка наличия строчных букв
        if not re.search(r'[a-z]', v):
            errors.append('Пароль должен содержать хотя бы одну строчную букву')
        
        # Проверка наличия цифр
        if not re.search(r'\d', v):
            errors.append('Пароль должен содержать хотя бы одну цифру')
        
        # Проверка наличия специальных символов
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            errors.append('Пароль должен содержать хотя бы один специальный символ')
        
        # Проверка на распространенные слабые пароли
        weak_passwords = ['password', '12345678', 'qwerty', 'admin', 'letmein']
        if v.lower() in weak_passwords:
            errors.append('Пароль слишком простой')
        
        if errors:
            raise ValueError('; '.join(errors))
        
        return v
    
    @validator('confirm_password')
    def validate_password_match(cls, v, values):
        """Проверка совпадения паролей."""
        if 'password' in values and v != values['password']:
            raise ValueError('Пароли не совпадают')
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "email": "user@example.com",
                "password": "StrongPass123!",
                "confirm_password": "StrongPass123!",
                "username": "john_doe",
                "first_name": "John",
                "last_name": "Doe"
            }
        }

class UserResponse(BaseModel):
    """Модель ответа после регистрации."""
    id: str
    email: str
    username: str
    first_name: Optional[str]
    last_name: Optional[str]
    created_at: datetime
    is_active: bool

# --- Security ---
class PasswordHasher:
    """Класс для хеширования и проверки паролей."""
    
    def __init__(self):
        # ИСПОЛЬЗУЕМ СОВРЕМЕННЫЕ АЛГОРИТМЫ ХЕШИРОВАНИЯ С СОЛЬЮ
        self.pwd_context = CryptContext(
            schemes=["bcrypt"],  # Используем bcrypt
            deprecated="auto",   # Автоматически обновлять устаревшие хеши
            bcrypt__rounds=12    # Количество раундов (баланс безопасности/производительности)
        )
    
    def hash_password(self, password: str) -> str:
        """
        Хеширование пароля.
        
        Args:
            password: Пароль в чистом виде
            
        Returns:
            Хешированный пароль
        """
        return self.pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Проверка пароля.
        
        Args:
            plain_password: Пароль в чистом виде
            hashed_password: Хешированный пароль
            
        Returns:
            True если пароль верный
        """
        return self.pwd_context.verify(plain_password, hashed_password)

# --- Database Layer ---
class DatabaseManager:
    """Менеджер для работы с базой данных."""
    
    def __init__(self, db_path: str = "users.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    first_name TEXT,
                    last_name TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TIMESTAMP
                )
            """)
            
            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для подключения к БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def user_exists(self, email: str, username: str) -> Dict[str, bool]:
        """
        Проверка существования пользователя.
        
        Args:
            email: Email для проверки
            username: Имя пользователя для проверки
            
        Returns:
            Словарь с результатами проверки
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # ПАРАМЕТРИЗОВАННЫЕ ЗАПРОСЫ для предотвращения SQL-инъекций
            cursor.execute(
                "SELECT COUNT(*) as count FROM users WHERE email = ? OR username = ?",
                (email, username)
            )
            
            result = cursor.fetchone()
            total = result['count'] if result else 0
            
            if total > 0:
                # Проверяем отдельно email и username
                cursor.execute(
                    "SELECT email, username FROM users WHERE email = ? OR username = ?",
                    (email, username)
                )
                
                exists = {'email': False, 'username': False}
                for row in cursor.fetchall():
                    if row['email'] == email:
                        exists['email'] = True
                    if row['username'] == username:
                        exists['username'] = True
                
                return exists
            
            return {'email': False, 'username': False}
    
    def create_user(self, user_data: Dict[str, Any]) -> Optional[str]:
        """
        Создание нового пользователя.
        
        Args:
            user_data: Данные пользователя
            
        Returns:
            ID созданного пользователя или None при ошибке
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Генерация UUID для пользователя
                user_id = str(uuid4())
                
                # ПАРАМЕТРИЗОВАННЫЙ ЗАПРОС
                cursor.execute("""
                    INSERT INTO users 
                    (id, email, username, password_hash, first_name, last_name, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    user_data['email'],
                    user_data['username'],
                    user_data['password_hash'],
                    user_data.get('first_name'),
                    user_data.get('last_name'),
                    datetime.now()
                ))
                
                conn.commit()
                return user_id
                
        except sqlite3.IntegrityError as e:
            logger.error(f"Integrity error creating user: {e}")
            return None
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Получение пользователя по ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

# --- Business Logic ---
class UserRegistrationService:
    """Сервис регистрации пользователей."""
    
    def __init__(self, db_manager: DatabaseManager, password_hasher: PasswordHasher):
        self.db = db_manager
        self.hasher = password_hasher
    
    def validate_registration_data(self, registration_data: UserRegistrationRequest) -> Dict[str, Any]:
        """
        Валидация данных регистрации.
        
        Args:
            registration_data: Данные для регистрации
            
        Returns:
            Словарь с результатами валидации
            
        Raises:
            HTTPException: При ошибках валидации
        """
        # Проверка существования пользователя
        exists = self.db.user_exists(
            registration_data.email, 
            registration_data.username
        )
        
        errors = []
        if exists['email']:
            errors.append("Пользователь с таким email уже существует")
        if exists['username']:
            errors.append("Пользователь с таким именем уже существует")
        
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(errors)
            )
        
        # Дополнительная бизнес-логика валидации
        # (например, проверка домена email, черные списки и т.д.)
        
        return {"valid": True}
    
    def register_user(self, registration_data: UserRegistrationRequest) -> UserResponse:
        """
        Основная процедура регистрации пользователя.
        
        Args:
            registration_data: Данные для регистрации
            
        Returns:
            Данные зарегистрированного пользователя
            
        Raises:
            HTTPException: При ошибках регистрации
        """
        try:
            # 1. Валидация данных
            self.validate_registration_data(registration_data)
            
            # 2. Хеширование пароля
            password_hash = self.hasher.hash_password(registration_data.password)
            
            # 3. Подготовка данных для сохранения
            user_data = {
                'email': registration_data.email,
                'username': registration_data.username,
                'password_hash': password_hash,
                'first_name': registration_data.first_name,
                'last_name': registration_data.last_name
            }
            
            # 4. Сохранение в базу данных
            user_id = self.db.create_user(user_data)
            
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Ошибка при создании пользователя"
                )
            
            # 5. Получение созданного пользователя
            user = self.db.get_user_by_id(user_id)
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Пользователь не найден после создания"
                )
            
            # 6. Логирование успешной регистрации
            logger.info(f"New user registered: {user['email']} (ID: {user_id})")
            
            # 7. Возврат результата
            return UserResponse(
                id=user['id'],
                email=user['email'],
                username=user['username'],
                first_name=user['first_name'],
                last_name=user['last_name'],
                created_at=datetime.fromisoformat(user['created_at']),
                is_active=bool(user['is_active'])
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Registration error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Внутренняя ошибка сервера"
            )

# --- Инициализация зависимостей ---
db_manager = DatabaseManager()
password_hasher = PasswordHasher()
registration_service = UserRegistrationService(db_manager, password_hasher)

# --- API Endpoints ---
@app.get("/health")
async def health_check():
    """Проверка работоспособности сервиса."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "user_registration"
    }

@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    registration_data: UserRegistrationRequest,
    request: Request
) -> UserResponse:
    """
    Эндпоинт регистрации нового пользователя.
    
    Args:
        registration_data: Данные для регистрации
        request: HTTP запрос
        
    Returns:
        Данные созданного пользователя
        
    Raises:
        HTTPException: При ошибках валидации или регистрации
    """
    try:
        # Логирование попытки регистрации
        client_ip = request.client.host if request.client else "unknown"
        logger.info(f"Registration attempt from {client_ip} for {registration_data.email}")
        
        # Вызов сервиса регистрации
        result = registration_service.register_user(registration_data)
        
        # Логирование успеха
        logger.info(f"Registration successful for {registration_data.email}")
        
        return result
        
    except HTTPException as e:
        # Логирование ошибок валидации
        logger.warning(f"Registration failed for {registration_data.email}: {e.detail}")
        raise e
        
    except Exception as e:
        # Логирование неожиданных ошибок
        logger.error(f"Unexpected registration error for {registration_data.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )

@app.post("/validate-password")
async def validate_password_strength(password: str):
    """
    Вспомогательный эндпоинт для проверки сложности пароля.
    
    Args:
        password: Пароль для проверки
        
    Returns:
        Результат проверки
    """
    try:
        # Используем валидатор из модели
        UserRegistrationRequest.validate_password_strength(password)
        
        return {
            "valid": True,
            "message": "Пароль соответствует требованиям безопасности",
            "strength": "strong"
        }
        
    except ValueError as e:
        return {
            "valid": False,
            "message": str(e),
            "strength": "weak"
        }

# --- Дополнительная функциональность ---
@app.get("/check-availability")
async def check_availability(email: str, username: str):
    """
    Проверка доступности email и имени пользователя.
    
    Args:
        email: Email для проверки
        username: Имя пользователя для проверки
        
    Returns:
        Результат проверки доступности
    """
    exists = db_manager.user_exists(email, username)
    
    return {
        "email_available": not exists['email'],
        "username_available": not exists['username'],
        "suggestions": {
            "email": f"Email {'уже используется' if exists['email'] else 'доступен'}",
            "username": f"Имя пользователя {'уже используется' if exists['username'] else 'доступен'}"
        }
    }

# --- Пример использования для тестирования ---
if __name__ == "__main__":
    import uvicorn
    
    # Запуск тестового сервера
    print("Starting User Registration Service...")
    print("Available endpoints:")
    print("  POST /register - регистрация пользователя")
    print("  POST /validate-password - проверка пароля")
    print("  GET /check-availability - проверка доступности email/username")
    print("  GET /health - проверка здоровья сервиса")
    
    uvicorn.run(app, host="0.0.0.0", port=8003)