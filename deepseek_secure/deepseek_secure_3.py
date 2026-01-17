from fastapi import FastAPI, HTTPException, Depends, status, Request
from pydantic import BaseModel, Field, ValidationError
from typing import Dict, Any, Optional, List
from enum import Enum
import json
from datetime import datetime
import sqlite3
from contextlib import contextmanager

app = FastAPI(title="Global Settings Service")

# --- Модели данных ---
class SettingType(str, Enum):
    """Типы настроек."""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"

class SettingSchema(BaseModel):
    """Схема валидации для настройки."""
    key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    type: SettingType
    default: Any
    constraints: Optional[Dict[str, Any]] = None
    required: bool = True

class SettingsUpdateRequest(BaseModel):
    """Модель запроса на обновление настроек."""
    settings: Dict[str, Any] = Field(..., description="Словарь настроек для обновления")
    
    class Config:
        extra = "forbid"  # Запрещаем передачу незаявленных полей

class SettingsResponse(BaseModel):
    """Модель ответа с настройками."""
    settings: Dict[str, Any]
    updated_at: datetime
    updated_by: str

# --- Роли пользователей ---
class UserRole(str, Enum):
    """Роли пользователей."""
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"

# --- Имитация текущего пользователя ---
class CurrentUser:
    """Класс для имитации текущего пользователя."""
    
    def __init__(self, username: str = "admin_user", role: UserRole = UserRole.ADMIN):
        self.username = username
        self.role = role
    
    def has_permission(self, required_role: UserRole) -> bool:
        """Проверка прав доступа."""
        role_hierarchy = {
            UserRole.ADMIN: [UserRole.ADMIN, UserRole.EDITOR, UserRole.VIEWER],
            UserRole.EDITOR: [UserRole.EDITOR, UserRole.VIEWER],
            UserRole.VIEWER: [UserRole.VIEWER]
        }
        return required_role in role_hierarchy.get(self.role, [])

def get_current_user(request: Request) -> CurrentUser:
    """
    Зависимость для получения текущего пользователя.
    В реальном приложении здесь будет проверка JWT или сессии.
    """
    # Имитация получения пользователя из заголовков
    username = request.headers.get("X-Username", "admin_user")
    role = request.headers.get("X-User-Role", UserRole.ADMIN)
    
    try:
        return CurrentUser(username=username, role=UserRole(role))
    except ValueError:
        # По умолчанию VIEWER если роль невалидна
        return CurrentUser(username=username, role=UserRole.VIEWER)

# --- Декоратор проверки прав ---
def require_role(required_role: UserRole):
    """
    Декоратор для проверки прав доступа к эндпоинту.
    
    Args:
        required_role: Требуемая роль для доступа
    """
    def decorator(endpoint):
        async def wrapped_endpoint(*args, request: Request, **kwargs):
            current_user = get_current_user(request)
            
            if not current_user.has_permission(required_role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Недостаточно прав для выполнения операции"
                )
            
            # Добавляем пользователя в kwargs
            kwargs['current_user'] = current_user
            return await endpoint(*args, **kwargs)
        
        return wrapped_endpoint
    
    return decorator

# --- Хранилище настроек ---
class SettingsStorage:
    """Класс для работы с хранилищем настроек."""
    
    def __init__(self, db_path: str = "settings.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица схем настроек
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS setting_schemas (
                    key TEXT PRIMARY KEY,
                    schema_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица значений настроек
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS setting_values (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT NOT NULL,
                    FOREIGN KEY (key) REFERENCES setting_schemas(key)
                )
            """)
            
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
    
    def get_setting_schema(self, key: str) -> Optional[SettingSchema]:
        """Получение схемы настройки."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT schema_json FROM setting_schemas WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            
            if row:
                return SettingSchema(**json.loads(row['schema_json']))
            return None
    
    def get_all_schemas(self) -> Dict[str, SettingSchema]:
        """Получение всех схем настроек."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, schema_json FROM setting_schemas")
            
            schemas = {}
            for row in cursor.fetchall():
                schemas[row['key']] = SettingSchema(**json.loads(row['schema_json']))
            
            return schemas
    
    def validate_setting(self, key: str, value: Any) -> bool:
        """
        Валидация значения настройки по схеме.
        
        Args:
            key: Ключ настройки
            value: Значение для валидации
            
        Returns:
            True если значение валидно
        """
        schema = self.get_setting_schema(key)
        if not schema:
            raise ValueError(f"Схема для настройки '{key}' не найдена")
        
        try:
            # Простая валидация типа
            if schema.type == SettingType.STRING:
                if not isinstance(value, str):
                    return False
                if schema.constraints and 'max_length' in schema.constraints:
                    if len(value) > schema.constraints['max_length']:
                        return False
            
            elif schema.type == SettingType.NUMBER:
                if not isinstance(value, (int, float)):
                    return False
                if schema.constraints:
                    if 'min' in schema.constraints and value < schema.constraints['min']:
                        return False
                    if 'max' in schema.constraints and value > schema.constraints['max']:
                        return False
            
            elif schema.type == SettingType.BOOLEAN:
                if not isinstance(value, bool):
                    return False
            
            # Для OBJECT и ARRAY проверяем только тип
            elif schema.type == SettingType.OBJECT:
                if not isinstance(value, dict):
                    return False
            
            elif schema.type == SettingType.ARRAY:
                if not isinstance(value, list):
                    return False
            
            return True
            
        except Exception:
            return False
    
    def update_settings(self, settings: Dict[str, Any], updated_by: str) -> datetime:
        """
        Обновление настроек в хранилище.
        
        Args:
            settings: Словарь настроек
            updated_by: Имя пользователя, выполняющего обновление
            
        Returns:
            Время обновления
        """
        current_time = datetime.now()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            for key, value in settings.items():
                # Проверяем существование схемы
                schema = self.get_setting_schema(key)
                if not schema:
                    raise ValueError(f"Настройка '{key}' не зарегистрирована")
                
                # Валидируем значение
                if not self.validate_setting(key, value):
                    raise ValueError(f"Некорректное значение для настройки '{key}'")
                
                # Обновляем значение
                cursor.execute("""
                    INSERT OR REPLACE INTO setting_values (key, value_json, updated_at, updated_by)
                    VALUES (?, ?, ?, ?)
                """, (key, json.dumps(value), current_time, updated_by))
            
            conn.commit()
        
        return current_time
    
    def get_all_settings(self) -> Dict[str, Any]:
        """Получение всех текущих значений настроек."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.key, 
                       COALESCE(v.value_json, s.schema_json->>'default') as value_json
                FROM setting_schemas s
                LEFT JOIN setting_values v ON s.key = v.key
            """)
            
            settings = {}
            for row in cursor.fetchall():
                try:
                    settings[row['key']] = json.loads(row['value_json'])
                except json.JSONDecodeError:
                    # Используем значение по умолчанию из схемы
                    schema = self.get_setting_schema(row['key'])
                    settings[row['key']] = schema.default if schema else None
            
            return settings

# --- Инициализация сервиса ---
settings_storage = SettingsStorage()

# Инициализация тестовых схем при старте
@app.on_event("startup")
async def initialize_default_schemas():
    """Инициализация тестовых схем настроек."""
    default_schemas = [
        SettingSchema(
            key="app_title",
            name="Название приложения",
            description="Основное название веб-приложения",
            type=SettingType.STRING,
            default="Мое приложение",
            constraints={"max_length": 100}
        ),
        SettingSchema(
            key="api_rate_limit",
            name="Лимит запросов к API",
            description="Максимальное количество запросов в минуту",
            type=SettingType.NUMBER,
            default=100,
            constraints={"min": 1, "max": 10000}
        ),
        SettingSchema(
            key="maintenance_mode",
            name="Режим техобслуживания",
            description="Включение режима техобслуживания",
            type=SettingType.BOOLEAN,
            default=False
        ),
        SettingSchema(
            key="feature_flags",
            name="Флаги функций",
            description="Включение/выключение экспериментальных функций",
            type=SettingType.OBJECT,
            default={"new_ui": False, "beta_features": True}
        )
    ]
    
    try:
        with settings_storage._get_connection() as conn:
            cursor = conn.cursor()
            
            for schema in default_schemas:
                cursor.execute("""
                    INSERT OR IGNORE INTO setting_schemas (key, schema_json)
                    VALUES (?, ?)
                """, (schema.key, schema.json()))
            
            conn.commit()
            print("Схемы настроек инициализированы")
            
    except Exception as e:
        print(f"Ошибка при инициализации схем: {e}")

# --- API Endpoints ---
@app.get("/settings", response_model=SettingsResponse)
async def get_settings(
    current_user: CurrentUser = Depends(get_current_user)
) -> SettingsResponse:
    """
    Получение всех текущих настроек.
    Доступно всем авторизованным пользователям.
    """
    settings = settings_storage.get_all_settings()
    
    # Получаем время последнего обновления
    with settings_storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MAX(updated_at) as last_updated, 
                   updated_by 
            FROM setting_values 
            WHERE updated_at = (SELECT MAX(updated_at) FROM setting_values)
        """)
        row = cursor.fetchone()
    
    return SettingsResponse(
        settings=settings,
        updated_at=datetime.fromisoformat(row['updated_at']) if row and row['last_updated'] else datetime.now(),
        updated_by=row['updated_by'] if row else "system"
    )

@app.put("/settings", response_model=SettingsResponse)
@require_role(UserRole.ADMIN)
async def update_settings(
    update_request: SettingsUpdateRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user)
) -> SettingsResponse:
    """
    Обновление настроек приложения.
    Требуются права администратора.
    
    Args:
        update_request: Запрос с новыми значениями настроек
        current_user: Текущий пользователь
        
    Returns:
        Обновленные настройки
    """
    try:
        # СТРОГАЯ ПРОВЕРКА ПРАВ НА СТОРОНЕ СЕРВЕРА
        if not current_user.has_permission(UserRole.ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Требуются права администратора"
            )
        
        # Дополнительная проверка: нельзя обновлять системные настройки
        system_keys = {"system_", "internal_", "secret_"}
        for key in update_request.settings.keys():
            if any(key.startswith(prefix) for prefix in system_keys):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Настройка '{key}' является системной"
                )
        
        # Обновляем настройки
        updated_at = settings_storage.update_settings(
            update_request.settings,
            current_user.username
        )
        
        # Получаем обновленные настройки
        settings = settings_storage.get_all_settings()
        
        # Логируем обновление
        print(f"Настройки обновлены пользователем {current_user.username}: "
              f"{list(update_request.settings.keys())}")
        
        return SettingsResponse(
            settings=settings,
            updated_at=updated_at,
            updated_by=current_user.username
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Ошибка при обновлении настроек: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)