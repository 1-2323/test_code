import secrets
import string
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from passlib.context import CryptContext


# =========================
# Конфигурация БД
# =========================

DATABASE_URL: str = "sqlite:///./app.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# =========================
# ORM-модель пользователя
# =========================

class User(Base):
    """
    Пользователь системы.
    """
    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True)
    username: str = Column(String, unique=True, nullable=False)
    password_hash: str = Column(String, nullable=False)
    is_admin: bool = Column(Boolean, default=False)
    must_change_password: bool = Column(Boolean, default=False)


# =========================
# Сервисы безопасности
# =========================

class PasswordHasher:
    """
    Сервис хеширования паролей.
    """

    _context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    @classmethod
    def hash(cls, password: str) -> str:
        return cls._context.hash(password)


class PasswordGenerator:
    """
    Генератор случайных паролей.
    """

    @staticmethod
    def generate(length: int = 14) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))


# =========================
# Репозиторий пользователей
# =========================

class UserRepository:
    """
    Репозиторий пользователей.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_admin(self) -> Optional[User]:
        return (
            self._db.query(User)
            .filter(User.is_admin.is_(True))
            .first()
        )

    def create_admin(
        self,
        username: str,
        password_hash: str,
    ) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            is_admin=True,
            must_change_password=True,
        )
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        return user


# =========================
# System Bootstrapper
# =========================

class SystemBootstrapper:
    """
    Скрипт инициализации системы при первом запуске.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        admin_username: str = "admin",
        admin_password: Optional[str] = None,
    ) -> None:
        self._users = user_repository
        self._admin_username = admin_username
        self._admin_password = admin_password

    def run(self) -> None:
        """
        Запускает процесс инициализации.
        """
        if self._users.get_admin():
            return

        password: str = (
            self._admin_password
            if self._admin_password
            else PasswordGenerator.generate()
        )

        password_hash = PasswordHasher.hash(password)

        self._users.create_admin(
            username=self._admin_username,
            password_hash=password_hash,
        )

        self._print_credentials(password)

    @staticmethod
    def _print_credentials(password: str) -> None:
        """
        Выводит временные учётные данные администратора.
        """
        print("=== ADMIN ACCOUNT CREATED ===")
        print("Username: admin")
        print(f"Temporary password: {password}")
        print("Password change is required on first login.")


# =========================
# Точка входа
# =========================

def init_database() -> None:
    """
    Создаёт таблицы БД.
    """
    Base.metadata.create_all(bind=engine)


def bootstrap() -> None:
    """
    Выполняет bootstrap приложения.
    """
    init_database()

    db = SessionLocal()
    try:
        user_repo = UserRepository(db)
        bootstrapper = SystemBootstrapper(user_repo)
        bootstrapper.run()
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap()
