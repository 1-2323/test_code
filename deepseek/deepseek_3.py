"""
Система управления конфигурацией с проверкой прав доступа и сохранением в файл/БД.
"""

import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, status, Body
from pydantic import BaseModel, Field, validator
import sqlite3


# ==================== МОДЕЛИ ДАННЫХ ====================

class ConfigFormat(str, Enum):
    """Форматы конфигурационных файлов."""
    JSON = "json"
    YAML = "yaml"


class APIRateLimit(BaseModel):
    """Модель лимитов API-запросов."""
    endpoint: str
    requests_per_minute: int = Field(..., gt=0)
    requests_per_hour: int = Field(..., gt=0)
    burst_limit: int = Field(5, gt=0, description="Максимальное количество запросов за раз")
    
    @validator('requests_per_hour')
    def validate_hourly_limit(cls, v, values):
        """Проверяет, что часовой лимит больше минутного."""
        if 'requests_per_minute' in values and v <= values['requests_per_minute']:
            raise ValueError("Часовой лимит должен быть больше минутного")
        return v


class GlobalSettings(BaseModel):
    """Основная модель глобальных настроек."""
    title: str = Field(..., min_length=1, max_length=100, description="Название приложения")
    api_rates: List[APIRateLimit] = Field(default_factory=list, description="Лимиты API")
    debug: bool = Field(False, description="Режим отладки")
    maintenance_mode: bool = Field(False, description="Режим технического обслуживания")
    version: str = Field("1.0.0", description="Версия конфигурации")
    updated_at: Optional[datetime] = Field(None, description="Время последнего обновления")
    
    class Config:
        """Конфигурация Pydantic модели."""
        schema_extra = {
            "example": {
                "title": "My Application",
                "api_rates": [
                    {
                        "endpoint": "/api/v1/users",
                        "requests_per_minute": 60,
                        "requests_per_hour": 1000,
                        "burst_limit": 10
                    }
                ],
                "debug": False,
                "maintenance_mode": False,
                "version": "1.0.0"
            }
        }


class SettingsUpdate(BaseModel):
    """Модель для обновления настроек."""
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    api_rates: Optional[List[APIRateLimit]] = None
    debug: Optional[bool] = None
    maintenance_mode: Optional[bool] = None
    
    @validator('api_rates')
    def validate_api_rates(cls, v):
        """Валидация лимитов API."""
        if v is not None:
            # Проверяем уникальность endpoint'ов
            endpoints = [rate.endpoint for rate in v]
            if len(endpoints) != len(set(endpoints)):
                raise ValueError("Endpoint'ы в api_rates должны быть уникальными")
        return v


# ==================== СИСТЕМА ПРАВ ДОСТУПА ====================

class UserRole(str, Enum):
    """Роли пользователей системы."""
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    GUEST = "guest"


@dataclass
class CurrentUser:
    """Модель текущего пользователя."""
    id: int
    username: str
    role: UserRole
    is_active: bool = True


class PermissionDeniedError(Exception):
    """Исключение для отказа в доступе."""
    pass


def require_permission(required_role: UserRole):
    """
    Декоратор для проверки прав доступа.
    
    Args:
        required_role: Минимальная требуемая роль для доступа.
    
    Returns:
        Декоратор для проверки прав.
    """
    def decorator(func: Callable):
        async def wrapper(
            current_user: CurrentUser = Depends(get_current_user),
            *args,
            **kwargs
        ):
            # Определяем порядок ролей по уровню доступа
            role_hierarchy = {
                UserRole.GUEST: 0,
                UserRole.VIEWER: 1,
                UserRole.EDITOR: 2,
                UserRole.ADMIN: 3
            }
            
            # Проверяем уровень доступа
            user_level = role_hierarchy.get(current_user.role, 0)
            required_level = role_hierarchy.get(required_role, 0)
            
            if user_level < required_level:
                raise PermissionDeniedError(
                    f"Требуется роль {required_role} или выше. "
                    f"Ваша роль: {current_user.role}"
                )
            
            if not current_user.is_active:
                raise PermissionDeniedError("Учетная запись неактивна")
            
            return await func(current_user, *args, **kwargs)
        
        return wrapper
    return decorator


# ==================== ХРАНИЛИЩА КОНФИГУРАЦИИ ====================

class SettingsStorage(ABC):
    """Абстрактный класс для хранения настроек."""
    
    @abstractmethod
    def load_settings(self) -> GlobalSettings:
        """Загружает настройки из хранилища."""
        pass
    
    @abstractmethod
    def save_settings(self, settings: GlobalSettings) -> bool:
        """Сохраняет настройки в хранилище."""
        pass


class JSONFileStorage(SettingsStorage):
    """Хранилище настроек в JSON файле."""
    
    def __init__(self, file_path: str = "config/settings.json"):
        """
        Инициализация JSON хранилища.
        
        Args:
            file_path: Путь к JSON файлу с настройками.
        """
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
    
    def load_settings(self) -> GlobalSettings:
        """
        Загружает настройки из JSON файла.
        
        Returns:
            GlobalSettings: Загруженные настройки.
            
        Raises:
            FileNotFoundError: Если файл не существует.
            ValueError: Если файл содержит невалидные данные.
        """
        if not self.file_path.exists():
            # Возвращаем настройки по умолчанию
            return GlobalSettings(
                title="Default Application",
                api_rates=[],
                debug=False,
                maintenance_mode=False
            )
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Преобразуем строки дат в объекты datetime
            if 'updated_at' in data and data['updated_at']:
                data['updated_at'] = datetime.fromisoformat(data['updated_at'])
            
            return GlobalSettings(**data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Ошибка декодирования JSON: {str(e)}")
        except Exception as e:
            raise ValueError(f"Ошибка загрузки настроек: {str(e)}")
    
    def save_settings(self, settings: GlobalSettings) -> bool:
        """
        Сохраняет настройки в JSON файл.
        
        Args:
            settings: Настройки для сохранения.
            
        Returns:
            bool: True если сохранение успешно.
        """
        try:
            # Обновляем timestamp
            settings.updated_at = datetime.now()
            
            # Преобразуем в словарь
            settings_dict = settings.dict()
            
            # Сериализуем datetime в строку
            if settings_dict['updated_at']:
                settings_dict['updated_at'] = settings_dict['updated_at'].isoformat()
            
            # Сохраняем в файл с красивым форматированием
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(settings_dict, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            print(f"Ошибка сохранения настроек: {str(e)}")
            return False


class DatabaseStorage(SettingsStorage):
    """Хранилище настроек в базе данных SQLite."""
    
    def __init__(self, db_path: str = "config/settings.db"):
        """
        Инициализация хранилища в БД.
        
        Args:
            db_path: Путь к файлу базы данных.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self) -> None:
        """Инициализирует таблицы базы данных."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS global_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    title TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
    
    def load_settings(self) -> GlobalSettings:
        """
        Загружает настройки из базы данных.
        
        Returns:
            GlobalSettings: Загруженные настройки.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM global_settings WHERE id = 1")
                row = cursor.fetchone()
                
                if row:
                    config_data = json.loads(row['config_json'])
                    config_data['title'] = row['title']
                    
                    if row['updated_at']:
                        config_data['updated_at'] = datetime.fromisoformat(row['updated_at'])
                    
                    return GlobalSettings(**config_data)
                else:
                    # Возвращаем настройки по умолчанию
                    return GlobalSettings(
                        title="Default Application",
                        api_rates=[],
                        debug=False,
                        maintenance_mode=False
                    )
        except Exception as e:
            raise ValueError(f"Ошибка загрузки настроек из БД: {str(e)}")
    
    def save_settings(self, settings: GlobalSettings) -> bool:
        """
        Сохраняет настройки в базу данных.
        
        Args:
            settings: Настройки для сохранения.
            
        Returns:
            bool: True если сохранение успешно.
        """
        try:
            # Подготавливаем данные
            settings.updated_at = datetime.now()
            settings_dict = settings.dict()
            
            # Извлекаем title и оставшиеся настройки
            title = settings_dict.pop('title')
            updated_at = settings_dict.pop('updated_at')
            
            # Сохраняем остальные настройки как JSON
            config_json = json.dumps(settings_dict)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Используем INSERT OR REPLACE для обновления единственной записи
                cursor.execute('''
                    INSERT OR REPLACE INTO global_settings 
                    (id, title, config_json, updated_at) 
                    VALUES (1, ?, ?, ?)
                ''', (title, config_json, updated_at.isoformat()))
                
                conn.commit()
            
            return True
        except Exception as e:
            print(f"Ошибка сохранения настроек в БД: {str(e)}")
            return False


# ==================== ОСНОВНОЙ СЕРВИС ====================

class GlobalSettingsService:
    """
    Основной сервис управления глобальными настройками.
    Предоставляет методы для загрузки, обновления и сохранения настроек.
    """
    
    def __init__(self, storage: SettingsStorage):
        """
        Инициализация сервиса настроек.
        
        Args:
            storage: Реализация интерфейса SettingsStorage.
        """
        self.storage = storage
        self._current_settings = self.load_settings()
    
    def load_settings(self) -> GlobalSettings:
        """
        Загружает текущие настройки из хранилища.
        
        Returns:
            GlobalSettings: Текущие настройки.
        """
        return self.storage.load_settings()
    
    def get_current_settings(self) -> GlobalSettings:
        """
        Возвращает текущие настройки (кешированные).
        
        Returns:
            GlobalSettings: Текущие настройки.
        """
        return self._current_settings
    
    def update_settings(
        self, 
        update_data: SettingsUpdate, 
        updated_by: str = "system"
    ) -> GlobalSettings:
        """
        Обновляет глобальные настройки.
        
        Args:
            update_data: Данные для обновления.
            updated_by: Идентификатор пользователя, внесшего изменения.
            
        Returns:
            GlobalSettings: Обновленные настройки.
            
        Raises:
            ValueError: Если данные обновления невалидны.
        """
        try:
            # Загружаем текущие настройки
            current_settings = self._current_settings.dict()
            
            # Применяем обновления
            update_dict = update_data.dict(exclude_unset=True)
            
            for key, value in update_dict.items():
                if value is not None:
                    current_settings[key] = value
            
            # Создаем новую модель настроек
            new_settings = GlobalSettings(**current_settings)
            
            # Сохраняем в хранилище
            if self.storage.save_settings(new_settings):
                self._current_settings = new_settings
                print(f"Настройки обновлены пользователем: {updated_by}")
                return new_settings
            else:
                raise ValueError("Ошибка сохранения настроек в хранилище")
                
        except Exception as e:
            raise ValueError(f"Ошибка обновления настроек: {str(e)}")


# ==================== FASTAPI ЗАВИСИМОСТИ ====================

def get_current_user() -> CurrentUser:
    """
    Зависимость для получения текущего пользователя.
    В реальном приложении здесь была бы аутентификация.
    """
    # Имитация аутентифицированного администратора
    return CurrentUser(
        id=1,
        username="admin_user",
        role=UserRole.ADMIN
    )


def get_settings_service() -> GlobalSettingsService:
    """
    Зависимость для получения сервиса настроек.
    
    Returns:
        GlobalSettingsService: Экземпляр сервиса настроек.
    """
    # Можно выбрать любое хранилище
    storage = JSONFileStorage("config/settings.json")
    # storage = DatabaseStorage("config/settings.db")
    return GlobalSettingsService(storage)


# ==================== FASTAPI ПРИЛОЖЕНИЕ ====================

app = FastAPI(
    title="Global Settings API",
    description="API для управления глобальными настройками приложения",
    version="1.0.0"
)


@app.get("/")
async def root():
    """Корневой эндпоинт."""
    return {
        "service": "Global Settings Manager",
        "version": "1.0.0",
        "endpoints": {
            "get_settings": "/api/settings",
            "update_settings": "/api/settings (PATCH)"
        }
    }


@app.get(
    "/api/settings",
    response_model=GlobalSettings,
    summary="Получить текущие настройки",
    description="Возвращает текущие глобальные настройки приложения.",
    dependencies=[Depends(require_permission(UserRole.VIEWER))]
)
async def get_settings(
    settings_service: GlobalSettingsService = Depends(get_settings_service)
) -> GlobalSettings:
    """
    Получает текущие глобальные настройки.
    
    Args:
        settings_service: Сервис управления настройками.
        
    Returns:
        GlobalSettings: Текущие настройки приложения.
    """
    return settings_service.get_current_settings()


@app.patch(
    "/api/settings",
    response_model=GlobalSettings,
    summary="Обновить настройки",
    description="""
    Обновляет глобальные настройки приложения.
    Требуются права администратора.
    """,
    responses={
        200: {"description": "Настройки успешно обновлены"},
        400: {"description": "Невалидные данные"},
        403: {"description": "Доступ запрещен"}
    }
)
@require_permission(UserRole.ADMIN)
async def update_settings(
    update_data: SettingsUpdate = Body(..., description="Данные для обновления настроек"),
    current_user: CurrentUser = Depends(get_current_user),
    settings_service: GlobalSettingsService = Depends(get_settings_service)
) -> GlobalSettings:
    """
    Обновляет глобальные настройки приложения.
    
    Args:
        update_data: Данные для обновления.
        current_user: Текущий пользователь (администратор).
        settings_service: Сервис управления настройками.
        
    Returns:
        GlobalSettings: Обновленные настройки.
        
    Raises:
        HTTPException: Если данные невалидны или доступ запрещен.
    """
    try:
        # Обновляем настройки
        updated_settings = settings_service.update_settings(
            update_data,
            updated_by=current_user.username
        )
        
        return updated_settings
        
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Внутренняя ошибка при обновлении настроек: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )


@app.get("/api/settings/health")
async def settings_health(
    settings_service: GlobalSettingsService = Depends(get_settings_service)
):
    """Проверка здоровья сервиса настроек."""
    try:
        settings = settings_service.get_current_settings()
        return {
            "status": "healthy",
            "settings_version": settings.version,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Сервис настроек недоступен: {str(e)}"
        )


# Пример запуска приложения
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)