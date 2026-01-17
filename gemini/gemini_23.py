import secrets
import string
import hashlib
from typing import Optional
from sqlalchemy import Column, Integer, String, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Base = declarative_base()

class User(Base):
    """Модель пользователя с флагом принудительной смены пароля."""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    # Флаг: если True, пользователь обязан сменить пароль при следующем входе
    must_change_password = Column(Boolean, default=False)

class SystemBootstrapper:
    """
    Утилита для первичной инициализации системы.
    Создает суперпользователя, если он отсутствует.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def _generate_secure_password(self, length: int = 16) -> str:
        """Генерирует криптостойкий случайный пароль."""
        alphabet = string.ascii_letters + string.digits + "!@#$%"
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def _hash_password(self, plain_password: str) -> str:
        """
        Упрощенное хеширование для примера (в продакшене использовать bcrypt/argon2).
        """
        return hashlib.sha256(plain_password.encode()).hexdigest()

    def ensure_admin_exists(self, username: str = "admin", preset_password: Optional[str] = None) -> None:
        """
        Создает администратора. Если пароль не передан, генерирует его.
        Устанавливает флаг must_change_password=True.
        """
        existing_user = self.db.query(User).filter(User.username == username).first()
        
        if existing_user:
            print(f"INFO: Пользователь '{username}' уже существует. Пропуск инициализации.")
            return

        # Определение пароля
        password_to_set = preset_password
        generated_automatically = False
        
        if not password_to_set:
            password_to_set = self._generate_secure_password()
            generated_automatically = True

        # Создание записи
        admin_user = User(
            username=username,
            password_hash=self._hash_password(password_to_set),
            is_admin=True,
            must_change_password=True  # Ключевое требование
        )

        try:
            self.db.add(admin_user)
            self.db.commit()
            
            print("=" * 60)
            print(f"SUCCESS: Администратор '{username}' успешно создан.")
            
            if generated_automatically:
                print(f"GENERATED PASSWORD: {password_to_set}")
                print("Сохраните этот пароль в надежном месте!")
            
            print("SECURITY ALERT: При первом входе система потребует смену пароля.")
            print("=" * 60)
            
        except Exception as e:
            self.db.rollback()
            print(f"CRITICAL: Ошибка при создании администратора: {e}")

# --- Запуск скрипта ---

if __name__ == "__main__":
    # Настройка БД
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        bootstrapper = SystemBootstrapper(session)
        
        # Сценарий 1: Автоматическая генерация пароля
        bootstrapper.ensure_admin_exists(username="superuser")
        
        # Сценарий 2: Повторный запуск (должен пропустить)
        bootstrapper.ensure_admin_exists(username="superuser")