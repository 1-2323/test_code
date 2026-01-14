import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, String, JSON, DateTime, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Конфигурация
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./settings.db")
CONFIG_FILE_PATH = Path(os.getenv("CONFIG_FILE_PATH", "./config/settings.json"))

# Инициализация FastAPI
app = FastAPI(title="Settings API")

# SQLAlchemy модели
Base = declarative_base()

class GlobalSettingsDB(Base):
    __tablename__ = "global_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    settings_key = Column(String(50), unique=True, index=True, nullable=False)
    settings_value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Создание таблиц
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

# Pydantic модели для валидации
class RateLimits(BaseModel):
    max_requests: int = Field(default=100, ge=1, le=10000)
    per_seconds: int = Field(default=60, ge=1, le=3600)

class GlobalSettingsModel(BaseModel):
    title: str = Field(default="My Application", min_length=1, max_length=255)
    maintenance_mode: bool = Field(default=False)
    api_rates: RateLimits = Field(default_factory=RateLimits)
    default_language: str = Field(default="ru", regex="^(ru|en|es|fr)$")
    max_upload_size: int = Field(default=10485760, ge=1024, le=1073741824)
    
    @validator('title')
    def validate_title(cls, v):
        if not v.strip():
            raise ValueError('Title cannot be empty or whitespace only')
        return v.strip()

class SettingsUpdateRequest(BaseModel):
    settings: GlobalSettingsModel

# Зависимости
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SettingsStorage:
    """Класс для управления хранением настроек (база данных и файл)"""
    
    @staticmethod
    def save_to_database(settings: Dict[str, Any], db: Session):
        """Сохранение настроек в базу данных"""
        settings_json = json.loads(json.dumps(settings, default=str))
        
        # Ищем существующую запись
        db_settings = db.query(GlobalSettingsDB).filter(
            GlobalSettingsDB.settings_key == "global"
        ).first()
        
        if db_settings:
            db_settings.settings_value = settings_json
            db_settings.updated_at = datetime.utcnow()
        else:
            db_settings = GlobalSettingsDB(
                settings_key="global",
                settings_value=settings_json
            )
            db.add(db_settings)
        
        db.commit()
        return db_settings
    
    @staticmethod
    def save_to_file(settings: Dict[str, Any]):
        """Сохранение настроек в JSON файл"""
        settings_data = {
            "settings": settings,
            "updated_at": datetime.utcnow().isoformat(),
            "version": "1.0"
        }
        
        # Создаем директорию если не существует
        CONFIG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем в файл
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def get_current_settings(db: Session) -> Optional[Dict[str, Any]]:
        """Получение текущих настроек из базы данных"""
        db_settings = db.query(GlobalSettingsDB).filter(
            GlobalSettingsDB.settings_key == "global"
        ).first()
        
        if db_settings and db_settings.settings_value:
            return db_settings.settings_value
        return None

# Эндпоинт
@app.post(
    "/api/settings/global",
    status_code=status.HTTP_200_OK,
    summary="Обновление глобальных настроек",
    response_description="Настройки успешно сохранены"
)
async def update_global_settings(
    request: SettingsUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Обновление глобальных настроек приложения.
    
    Принимает JSON с настройками и сохраняет их в базу данных и файл конфигурации.
    
    - **title**: Название приложения
    - **maintenance_mode**: Режим технического обслуживания
    - **api_rates**: Настройки ограничения запросов API
    - **default_language**: Язык по умолчанию
    - **max_upload_size**: Максимальный размер загружаемого файла
    """
    try:
        # Конвертируем Pydantic модель в словарь
        settings_dict = request.settings.dict()
        
        # Сохраняем в базу данных
        SettingsStorage.save_to_database(settings_dict, db)
        
        # Сохраняем в файл
        SettingsStorage.save_to_file(settings_dict)
        
        # Получаем обновленные настройки для ответа
        current_settings = SettingsStorage.get_current_settings(db)
        
        return {
            "status": "success",
            "message": "Global settings updated successfully",
            "data": current_settings,
            "updated_at": datetime.utcnow().isoformat(),
            "storage_locations": {
                "database": True,
                "config_file": str(CONFIG_FILE_PATH)
            }
        }
        
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON format: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation error: {str(e)}"
        )
    except IOError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save settings to file: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )

# Дополнительный эндпоинт для получения текущих настроек
@app.get(
    "/api/settings/global",
    summary="Получение текущих глобальных настроек"
)
async def get_global_settings(db: Session = Depends(get_db)):
    """Получение текущих глобальных настроек приложения"""
    settings = SettingsStorage.get_current_settings(db)
    
    if not settings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Settings not found"
        )
    
    return {
        "status": "success",
        "data": settings
    }

# Запуск приложения (для разработки)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)