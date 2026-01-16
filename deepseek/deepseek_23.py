# app/bootstrap/system_bootstrapper.py
import os
import secrets
import string
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

# Загрузка переменных окружения
load_dotenv()


class SystemBootstrapper:
    """
    Класс для начальной настройки системы при первом запуске
    Создает административную учетную запись с принудительной сменой пароля
    """
    
    def __init__(self, db_session: Session):
        """
        Инициализация бутстраппера
        
        Args:
            db_session: Сессия базы данных SQLAlchemy
        """
        self.db_session = db_session
    
    def generate_random_password(self, length: int = 16) -> str:
        """
        Генерация случайного пароля
        
        Args:
            length: Длина пароля
            
        Returns:
            Случайный пароль
        """
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def create_admin_user(self) -> dict:
        """
        Создание административной учетной записи
        
        Returns:
            Словарь с данными администратора
        """
        from app.models.user import User  # Импорт здесь, чтобы избежать циклических зависимостей
        
        # Чтение конфигурации из переменных окружения
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD")
        
        # Проверка, существует ли уже администратор
        existing_admin = self.db_session.query(User).filter(
            User.email == admin_email
        ).first()
        
        if existing_admin:
            return {
                "status": "skipped",
                "message": "Admin user already exists",
                "email": admin_email
            }
        
        # Генерация пароля, если не задан
        if not admin_password:
            admin_password = self.generate_random_password()
            print(f"Generated admin password: {admin_password}")
        
        try:
            # Создание администратора
            admin_user = User(
                email=admin_email,
                username=admin_username,
                password=admin_password,  # На практике пароль должен быть хеширован
                is_active=True,
                is_admin=True,
                is_superuser=True,
                password_change_required=True,  # Требовать смену пароля при первом входе
                created_at=datetime.utcnow()
            )
            
            self.db_session.add(admin_user)
            self.db_session.commit()
            
            return {
                "status": "created",
                "message": "Admin user created successfully",
                "email": admin_email,
                "password": admin_password if not os.getenv("ADMIN_PASSWORD") else "[PROVIDED]",
                "password_change_required": True
            }
            
        except IntegrityError as e:
            self.db_session.rollback()
            return {
                "status": "error",
                "message": f"Failed to create admin user: {str(e)}"
            }
    
    def bootstrap(self) -> dict:
        """
        Выполняет все начальные настройки системы
        
        Returns:
            Словарь с результатами бутстрапа
        """
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "steps": {}
        }
        
        # Шаг 1: Создание администратора
        results["steps"]["admin_creation"] = self.create_admin_user()
        
        # Шаг 2: Проверка конфигурации (можно добавить дополнительные проверки)
        results["steps"]["config_validation"] = self.validate_configuration()
        
        # Шаг 3: Создание необходимых директорий
        results["steps"]["directories_setup"] = self.setup_directories()
        
        return results
    
    def validate_configuration(self) -> dict:
        """
        Проверка обязательных конфигурационных параметров
        
        Returns:
            Результаты проверки
        """
        required_vars = [
            "SECRET_KEY",
            "DATABASE_URL",
        ]
        
        missing = []
        for var in required_vars:
            if not os.getenv(var):
                missing.append(var)
        
        return {
            "status": "valid" if not missing else "invalid",
            "missing_variables": missing,
            "message": f"Missing required variables: {missing}" if missing else "All required variables are set"
        }
    
    def setup_directories(self) -> dict:
        """
        Создание необходимых директорий для работы приложения
        
        Returns:
            Результаты создания директорий
        """
        directories = [
            "logs",
            "uploads",
            "temp"
        ]
        
        created = []
        errors = []
        
        for directory in directories:
            try:
                os.makedirs(directory, exist_ok=True)
                created.append(directory)
            except Exception as e:
                errors.append(f"{directory}: {str(e)}")
        
        return {
            "status": "completed" if not errors else "partial",
            "created": created,
            "errors": errors
        }


def run_bootstrap() -> None:
    """
    Основная функция запуска бутстрапа системы
    """
    from app.database import SessionLocal  # Импорт здесь, чтобы избежать циклических зависимостей
    
    db_session = SessionLocal()
    
    try:
        bootstrapper = SystemBootstrapper(db_session)
        results = bootstrapper.bootstrap()
        
        print("=" * 50)
        print("SYSTEM BOOTSTRAP RESULTS")
        print("=" * 50)
        
        for step, result in results["steps"].items():
            print(f"\n{step.upper()}:")
            for key, value in result.items():
                print(f"  {key}: {value}")
        
        print("\n" + "=" * 50)
        
        # Важные предупреждения
        if results["steps"]["admin_creation"].get("password_change_required"):
            print("\n⚠️  IMPORTANT: Admin must change password on first login!")
        
        if results["steps"]["config_validation"]["status"] == "invalid":
            print("\n❌ CONFIGURATION ISSUES DETECTED!")
        
    finally:
        db_session.close()


if __name__ == "__main__":
    run_bootstrap()