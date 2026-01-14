import asyncio
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import hashlib
import secrets
import string

# Добавляем путь к проекту в PYTHONPATH
sys.path.append(str(Path(__file__).parent))

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel, EmailStr, validator, Field
from fastapi import Depends, FastAPI, HTTPException, status
from passlib.context import CryptContext
import click

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Константы для генерации пароля
PASSWORD_LENGTH = 12
ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@example.com"

# Модель базы данных
Base = declarative_base()

class User(Base):
    """Модель пользователя в базе данных"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(100))
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}')>"

# Pydantic схемы
class UserCreate(BaseModel):
    """Схема для создания пользователя"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=100)
    password: str = Field(..., min_length=8)
    is_superuser: bool = False
    
    @validator('username')
    def username_alphanumeric(cls, v):
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError('Имя пользователя должно содержать только буквы, цифры, дефисы и подчеркивания')
        return v.lower()

class UserResponse(BaseModel):
    """Схема для ответа с данными пользователя"""
    id: int
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    is_superuser: bool
    is_verified: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class AdminInitConfig(BaseModel):
    """Конфигурация инициализации администратора"""
    database_url: str
    admin_username: str = ADMIN_USERNAME
    admin_email: str = ADMIN_EMAIL
    admin_password: Optional[str] = None
    force_recreate: bool = False
    skip_if_exists: bool = True

class DatabaseManager:
    """Менеджер для работы с базой данных"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    def get_db(self):
        """Зависимость для получения сессии базы данных"""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    def init_database(self):
        """Инициализация базы данных (создание таблиц)"""
        logger.info(f"Инициализация базы данных: {self.database_url}")
        Base.metadata.create_all(bind=self.engine)
        logger.info("Таблицы базы данных созданы успешно")
    
    def drop_database(self):
        """Удаление всех таблиц базы данных"""
        logger.warning(f"Удаление всех таблиц базы данных: {self.database_url}")
        Base.metadata.drop_all(bind=self.engine)
        logger.info("Таблицы базы данных удалены")
    
    def get_password_hash(self, password: str) -> str:
        """Хеширование пароля"""
        return self.pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Проверка пароля"""
        return self.pwd_context.verify(plain_password, hashed_password)
    
    def generate_secure_password(self, length: int = PASSWORD_LENGTH) -> str:
        """Генерация безопасного пароля"""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password
    
    def user_exists(self, db: Session, username: str, email: str) -> bool:
        """Проверка существования пользователя"""
        user = db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        return user is not None
    
    def get_user(self, db: Session, username: str) -> Optional[User]:
        """Получение пользователя по имени"""
        return db.query(User).filter(User.username == username).first()
    
    def create_user(self, db: Session, user_data: UserCreate) -> User:
        """Создание нового пользователя"""
        hashed_password = self.get_password_hash(user_data.password)
        
        db_user = User(
            username=user_data.username,
            email=user_data.email,
            full_name=user_data.full_name,
            hashed_password=hashed_password,
            is_superuser=user_data.is_superuser,
            is_verified=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        logger.info(f"Создан пользователь: {db_user.username} (ID: {db_user.id})")
        return db_user
    
    def update_user_password(self, db: Session, user: User, new_password: str) -> User:
        """Обновление пароля пользователя"""
        user.hashed_password = self.get_password_hash(new_password)
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user
    
    def make_user_admin(self, db: Session, user: User) -> User:
        """Назначение пользователя администратором"""
        user.is_superuser = True
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

class AdminInitializer:
    """Класс для инициализации администратора"""
    
    def __init__(self, config: AdminInitConfig):
        self.config = config
        self.db_manager = DatabaseManager(config.database_url)
    
    def initialize(self) -> Dict[str, Any]:
        """Основной метод инициализации администратора"""
        
        result = {
            "success": False,
            "message": "",
            "admin_user": None,
            "generated_password": None
        }
        
        try:
            # Инициализация базы данных
            self.db_manager.init_database()
            
            db = next(self.db_manager.get_db())
            
            # Проверка существования администратора
            if self.db_manager.user_exists(db, self.config.admin_username, self.config.admin_email):
                if self.config.skip_if_exists and not self.config.force_recreate:
                    result["message"] = f"Администратор '{self.config.admin_username}' уже существует. Используйте --force-recreate для пересоздания."
                    result["admin_user"] = self.db_manager.get_user(db, self.config.admin_username)
                    return result
                
                if self.config.force_recreate:
                    # Удаляем существующего пользователя
                    existing_user = self.db_manager.get_user(db, self.config.admin_username)
                    if existing_user:
                        db.delete(existing_user)
                        db.commit()
                        logger.warning(f"Удален существующий пользователь: {self.config.admin_username}")
            
            # Генерация пароля если не указан
            password = self.config.admin_password
            if not password:
                password = self.db_manager.generate_secure_password()
                result["generated_password"] = password
            
            # Создание пользователя администратора
            user_data = UserCreate(
                username=self.config.admin_username,
                email=self.config.admin_email,
                full_name="System Administrator",
                password=password,
                is_superuser=True
            )
            
            admin_user = self.db_manager.create_user(db, user_data)
            
            result["success"] = True
            result["message"] = f"Администратор '{self.config.admin_username}' успешно создан"
            result["admin_user"] = admin_user
            
            logger.info(f"Администратор создан: {admin_user.username}")
            
        except Exception as e:
            result["message"] = f"Ошибка при создании администратора: {str(e)}"
            logger.error(f"Ошибка инициализации: {str(e)}", exc_info=True)
        
        finally:
            if 'db' in locals():
                db.close()
        
        return result
    
    def print_results(self, result: Dict[str, Any]):
        """Вывод результатов инициализации"""
        
        print("\n" + "="*60)
        print("РЕЗУЛЬТАТ ИНИЦИАЛИЗАЦИИ АДМИНИСТРАТОРА")
        print("="*60)
        
        if result["success"]:
            print(f"✓ {result['message']}")
            print(f"  ID: {result['admin_user'].id}")
            print(f"  Имя пользователя: {result['admin_user'].username}")
            print(f"  Email: {result['admin_user'].email}")
            print(f"  Суперадминистратор: {'Да' if result['admin_user'].is_superuser else 'Нет'}")
            
            if result["generated_password"]:
                print(f"\n⚠️  ВНИМАНИЕ: Сгенерирован пароль администратора")
                print(f"   Пароль: {result['generated_password']}")
                print(f"   Сохраните этот пароль в безопасном месте!")
            
            print(f"\n  Дата создания: {result['admin_user'].created_at}")
        
        else:
            print(f"✗ {result['message']}")
        
        print("="*60 + "\n")

def load_config_from_env() -> Optional[AdminInitConfig]:
    """Загрузка конфигурации из переменных окружения"""
    
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None
    
    return AdminInitConfig(
        database_url=database_url,
        admin_username=os.getenv("ADMIN_USERNAME", ADMIN_USERNAME),
        admin_email=os.getenv("ADMIN_EMAIL", ADMIN_EMAIL),
        admin_password=os.getenv("ADMIN_PASSWORD"),
        force_recreate=os.getenv("FORCE_RECREATE", "false").lower() == "true",
        skip_if_exists=os.getenv("SKIP_IF_EXISTS", "true").lower() == "true"
    )

# CLI команды с использованием Click
@click.group()
def cli():
    """CLI для управления инициализацией администратора"""
    pass

@cli.command()
@click.option('--database-url', required=True, help='URL подключения к базе данных')
@click.option('--admin-username', default=ADMIN_USERNAME, help='Имя пользователя администратора')
@click.option('--admin-email', default=ADMIN_EMAIL, help='Email администратора')
@click.option('--admin-password', help='Пароль администратора (если не указан, будет сгенерирован)')
@click.option('--force-recreate', is_flag=True, help='Принудительно пересоздать администратора если существует')
@click.option('--skip-if-exists', is_flag=True, default=True, help='Пропустить если администратор уже существует')
def init_admin(database_url, admin_username, admin_email, admin_password, force_recreate, skip_if_exists):
    """Инициализировать администратора в системе"""
    
    config = AdminInitConfig(
        database_url=database_url,
        admin_username=admin_username,
        admin_email=admin_email,
        admin_password=admin_password,
        force_recreate=force_recreate,
        skip_if_exists=skip_if_exists
    )
    
    initializer = AdminInitializer(config)
    result = initializer.initialize()
    initializer.print_results(result)
    
    if not result["success"]:
        sys.exit(1)

@cli.command()
@click.option('--database-url', required=True, help='URL подключения к базе данных')
def reset_database(database_url):
    """Удалить и пересоздать все таблицы базы данных (ОПАСНО!)"""
    
    if not click.confirm('Вы уверены, что хотите удалить все таблицы базы данных?'):
        click.echo("Отменено")
        return
    
    if not click.confirm('Это действие необратимо. Продолжить?'):
        click.echo("Отменено")
        return
    
    try:
        db_manager = DatabaseManager(database_url)
        db_manager.drop_database()
        db_manager.init_database()
        click.echo("✓ База данных сброшена и пересоздана")
    except Exception as e:
        click.echo(f"✗ Ошибка: {str(e)}")
        sys.exit(1)

@cli.command()
@click.option('--database-url', required=True, help='URL подключения к базе данных')
@click.option('--username', required=True, help='Имя пользователя для проверки')
def check_user(database_url, username):
    """Проверить существование пользователя"""
    
    try:
        db_manager = DatabaseManager(database_url)
        db = next(db_manager.get_db())
        user = db_manager.get_user(db, username)
        
        if user:
            click.echo(f"✓ Пользователь '{username}' найден:")
            click.echo(f"  ID: {user.id}")
            click.echo(f"  Email: {user.email}")
            click.echo(f"  Администратор: {'Да' if user.is_superuser else 'Нет'}")
            click.echo(f"  Активен: {'Да' if user.is_active else 'Нет'}")
        else:
            click.echo(f"✗ Пользователь '{username}' не найден")
            
    except Exception as e:
        click.echo(f"✗ Ошибка: {str(e)}")
        sys.exit(1)

async def async_main():
    """Асинхронная основная функция для использования внутри FastAPI приложения"""
    
    # Попытка загрузить конфигурацию из .env файла
    config = load_config_from_env()
    
    if not config:
        logger.error("Не удалось загрузить конфигурацию из .env файла")
        logger.info("Создайте файл .env со следующими переменными:")
        logger.info("DATABASE_URL=postgresql://user:password@localhost/dbname")
        logger.info("ADMIN_USERNAME=admin (опционально)")
        logger.info("ADMIN_EMAIL=admin@example.com (опционально)")
        logger.info("ADMIN_PASSWORD=secret (опционально)")
        return False
    
    # Инициализация администратора
    initializer = AdminInitializer(config)
    result = initializer.initialize()
    
    # Вывод результатов
    if result["success"]:
        logger.info(f"Администратор успешно инициализирован: {result['admin_user'].username}")
        if result["generated_password"]:
            logger.warning(f"Сгенерированный пароль: {result['generated_password']}")
            logger.warning("Сохраните этот пароль в безопасном месте!")
    else:
        logger.error(f"Ошибка инициализации: {result['message']}")
    
    return result["success"]

def main():
    """Основная функция для запуска из командной строки"""
    
    # Если есть аргументы командной строки, используем Click
    if len(sys.argv) > 1:
        cli()
    else:
        # Иначе запускаем автоматическую инициализацию
        print("Автоматическая инициализация администратора...")
        
        success = asyncio.run(async_main())
        
        if not success:
            print("\nИспользуйте команды:")
            print("  python init_admin.py init-admin --help")
            print("  python init_admin.py --help")
            sys.exit(1)

# Интеграция с FastAPI приложением
def setup_admin_on_startup(app: FastAPI, database_url: str):
    """Настройка автоматической инициализации администратора при запуске FastAPI"""
    
    @app.on_event("startup")
    async def startup_event():
        """Событие запуска приложения"""
        logger.info("Запуск инициализации администратора...")
        
        config = AdminInitConfig(
            database_url=database_url,
            skip_if_exists=True,
            force_recreate=False
        )
        
        initializer = AdminInitializer(config)
        result = initializer.initialize()
        
        if result["success"]:
            logger.info(f"Администратор инициализирован: {result['admin_user'].username}")
            
            # Сохраняем информацию об администраторе в состоянии приложения
            app.state.admin_initialized = True
            app.state.admin_user = result["admin_user"]
            
            if result["generated_password"]:
                logger.warning(f"Сгенерированный пароль сохранен в логах")
                # В продакшене пароль должен быть записан в безопасное место
        else:
            logger.warning(f"Администратор не создан: {result['message']}")
            app.state.admin_initialized = False

# Пример использования в FastAPI приложении
def create_fastapi_app(database_url: str) -> FastAPI:
    """Создание FastAPI приложения с автоматической инициализацией администратора"""
    
    app = FastAPI(title="Admin Initialization Example", version="1.0.0")
    
    # Настройка инициализации администратора при запуске
    setup_admin_on_startup(app, database_url)
    
    # Пример маршрута для проверки состояния
    @app.get("/admin/status")
    async def get_admin_status():
        """Получить статус инициализации администратора"""
        return {
            "admin_initialized": getattr(app.state, 'admin_initialized', False),
            "admin_user": getattr(app.state, 'admin_user', None)
        }
    
    return app

if __name__ == "__main__":
    main()