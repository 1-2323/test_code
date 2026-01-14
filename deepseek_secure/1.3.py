import json
import os
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, request, jsonify, g
from flask_jwt_extended import JWTManager, verify_jwt_in_request, get_jwt_identity
from pydantic import BaseModel, ValidationError, Field
import redis
from sqlalchemy import create_engine, Column, String, Boolean, Integer, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Инициализация приложения
app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
app.config['REDIS_URL'] = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
app.config['DATABASE_URL'] = os.getenv('DATABASE_URL', 'sqlite:///settings.db')

# Инициализация JWT
jwt = JWTManager(app)

# Подключение к Redis для кэширования
redis_client = redis.from_url(app.config['REDIS_URL'])

# Настройка SQLAlchemy
Base = declarative_base()
engine = create_engine(app.config['DATABASE_URL'])
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Модель для хранения настроек в БД
class GlobalSettingsDB(Base):
    __tablename__ = "global_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    settings_key = Column(String(50), unique=True, index=True, nullable=False)
    settings_data = Column(JSON, nullable=False)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Модель пользователя (упрощенная, для демонстрации)
class UserDB(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    role = Column(String(20), default='user', nullable=False)

# Pydantic модель для валидации входных данных
class GlobalSettingsUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    maintenance_mode: Optional[bool] = None
    api_rates: Optional[Dict[str, Any]] = None
    max_file_size: Optional[int] = Field(None, ge=1, le=1000)
    enable_registration: Optional[bool] = None
    
    class Config:
        extra = 'forbid'  # Запрещаем дополнительные поля

# Декоратор для проверки прав администратора
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        
        # Получаем идентификатор пользователя из JWT
        user_id = get_jwt_identity()
        
        # Получаем информацию о пользователе из базы данных
        db = SessionLocal()
        try:
            user = db.query(UserDB).filter(UserDB.id == user_id).first()
            
            if not user:
                return jsonify({"error": "Пользователь не найден"}), 404
            
            # Проверяем, является ли пользователь администратором
            if not user.is_admin and user.role != 'SuperAdmin':
                return jsonify({"error": "Недостаточно прав. Требуется роль администратора"}), 403
                
            # Сохраняем информацию о пользователе в g для использования в обработчике
            g.current_user = user
            return fn(*args, **kwargs)
        finally:
            db.close()
            
    return wrapper

# Класс для работы с настройками
class GlobalSettingsManager:
    SETTINGS_KEY = "global_app_settings"
    CACHE_KEY = "global_settings_cache"
    CACHE_TTL = 300  # 5 минут
    
    @classmethod
    def get_settings(cls) -> Dict[str, Any]:
        """Получение настроек с кэшированием"""
        # Пытаемся получить из кэша
        cached = redis_client.get(cls.CACHE_KEY)
        if cached:
            return json.loads(cached)
        
        # Если нет в кэше, получаем из базы
        db = SessionLocal()
        try:
            settings_record = db.query(GlobalSettingsDB)\
                .filter(GlobalSettingsDB.settings_key == cls.SETTINGS_KEY)\
                .first()
            
            if settings_record:
                settings = settings_record.settings_data
            else:
                # Возвращаем настройки по умолчанию
                settings = cls.get_default_settings()
                
            # Сохраняем в кэш
            redis_client.setex(cls.CACHE_KEY, cls.CACHE_TTL, json.dumps(settings))
            return settings
        finally:
            db.close()
    
    @classmethod
    def update_settings(cls, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Обновление глобальных настроек"""
        # Получаем текущие настройки
        current_settings = cls.get_settings()
        
        # Обновляем только переданные поля
        for key, value in new_settings.items():
            if value is not None:
                current_settings[key] = value
        
        # Сохраняем в базу данных
        db = SessionLocal()
        try:
            settings_record = db.query(GlobalSettingsDB)\
                .filter(GlobalSettingsDB.settings_key == cls.SETTINGS_KEY)\
                .first()
            
            if settings_record:
                settings_record.settings_data = current_settings
            else:
                settings_record = GlobalSettingsDB(
                    settings_key=cls.SETTINGS_KEY,
                    settings_data=current_settings
                )
                db.add(settings_record)
            
            db.commit()
            
            # Инвалидируем кэш
            redis_client.delete(cls.CACHE_KEY)
            
            return current_settings
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    
    @staticmethod
    def get_default_settings() -> Dict[str, Any]:
        """Настройки по умолчанию"""
        return {
            "title": "Мой Сайт",
            "maintenance_mode": False,
            "api_rates": {
                "max_requests_per_minute": 60,
                "max_requests_per_hour": 1000
            },
            "max_file_size": 10,  # MB
            "enable_registration": True,
            "updated_at": None,
            "updated_by": None
        }
    
    @staticmethod
    def save_to_file(settings: Dict[str, Any], filename: str = "global_settings_backup.json"):
        """Создание резервной копии настроек в файл"""
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)
        
        backup_path = backup_dir / filename
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

# Эндпоинт для обновления глобальных настроек
@app.route('/api/settings/global', methods=['POST'])
@admin_required
def update_global_settings():
    """
    Обновление глобальных настроек приложения.
    Требуется роль администратора или SuperAdmin.
    """
    try:
        # Валидация входных данных
        update_data = GlobalSettingsUpdate(**request.get_json())
        
        # Фильтруем None значения
        update_dict = {k: v for k, v in update_data.dict().items() if v is not None}
        
        if not update_dict:
            return jsonify({"error": "Нет данных для обновления"}), 400
        
        # Добавляем метаданные об обновлении
        update_dict['updated_at'] = json.dumps({'timestamp': '2024-01-01T00:00:00Z'})  # В реальности использовать datetime.utcnow()
        update_dict['updated_by'] = g.current_user.username
        
        # Обновляем настройки
        updated_settings = GlobalSettingsManager.update_settings(update_dict)
        
        # Создаем резервную копию
        GlobalSettingsManager.save_to_file(updated_settings)
        
        # Логируем действие
        app.logger.info(
            f"Глобальные настройки обновлены пользователем {g.current_user.username} "
            f"(ID: {g.current_user.id})"
        )
        
        return jsonify({
            "message": "Настройки успешно обновлены",
            "settings": updated_settings
        }), 200
        
    except ValidationError as e:
        return jsonify({"error": "Ошибка валидации", "details": e.errors()}), 400
    except json.JSONDecodeError:
        return jsonify({"error": "Неверный формат JSON"}), 400
    except Exception as e:
        app.logger.error(f"Ошибка при обновлении настроек: {str(e)}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

# Эндпоинт для получения текущих настроек (публичный)
@app.route('/api/settings/global', methods=['GET'])
def get_global_settings():
    """Получение текущих глобальных настроек"""
    try:
        settings = GlobalSettingsManager.get_settings()
        
        # Фильтруем чувствительные данные для обычных пользователей
        filtered_settings = {
            "title": settings.get("title"),
            "maintenance_mode": settings.get("maintenance_mode"),
            "enable_registration": settings.get("enable_registration")
        }
        
        return jsonify({"settings": filtered_settings}), 200
    except Exception as e:
        app.logger.error(f"Ошибка при получении настроек: {str(e)}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true')