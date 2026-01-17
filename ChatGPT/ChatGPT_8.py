import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    create_engine,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship


# =========================
# Конфигурация БД
# =========================

DATABASE_URL: str = "sqlite:///./password_reset.db"

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
# SQLAlchemy-модели
# =========================

class User(Base):
    """
    ORM-модель пользователя.
    """
    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True)
    email: str = Column(String, unique=True, nullable=False)

    reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="user",
    )


class PasswordResetToken(Base):
    """
    ORM-модель токена восстановления пароля.
    """
    __tablename__ = "password_reset_tokens"

    id: int = Column(Integer, primary_key=True)
    token: str = Column(String, unique=True, nullable=False, index=True)
    created_at: datetime = Column(DateTime, nullable=False)
    expires_at: datetime = Column(DateTime, nullable=False)

    user_id: int = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="reset_tokens")


# =========================
# Репозиторий
# =========================

class PasswordResetRepository:
    """
    Репозиторий для работы с токенами восстановления.
    """

    def __init__(self, db: Session) -> None:
        self._db: Session = db

    def save_token(
        self,
        user: User,
        token: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        """
        Сохраняет токен восстановления в БД.
        """
        reset_token = PasswordResetToken(
            token=token,
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            user=user,
        )
        self._db.add(reset_token)
        self._db.commit()
        self._db.refresh(reset_token)
        return reset_token

    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Возвращает пользователя по email.
        """
        return self._db.query(User).filter(User.email == email).first()


# =========================
# Сервис восстановления доступа
# =========================

class PasswordResetManager:
    """
    Сервис управления восстановлением доступа пользователя.
    """

    TOKEN_TTL_MINUTES: int = 30

    def __init__(
        self,
        repository: PasswordResetRepository,
        base_reset_url: str,
    ) -> None:
        self._repository: PasswordResetRepository = repository
        self._base_reset_url: str = base_reset_url

    def create_reset_link(self, email: str) -> str:
        """
        Создаёт ссылку восстановления пароля для пользователя.

        Алгоритм:
        1. Поиск пользователя по email
        2. Генерация уникального токена
        3. Сохранение токена с датой истечения
        4. Формирование URL восстановления

        :param email: email пользователя
        :return: URL для восстановления пароля
        """
        user: Optional[User] = self._repository.get_user_by_email(email)

        if user is None:
            raise ValueError("User with this email does not exist")

        token: str = self._generate_token()
        expires_at: datetime = self._calculate_expiration_time()

        self._repository.save_token(
            user=user,
            token=token,
            expires_at=expires_at,
        )

        return self._build_reset_url(token)

    # =========================
    # Внутренние методы
    # =========================

    @staticmethod
    def _generate_token() -> str:
        """
        Генерирует криптографически безопасный токен.
        """
        return secrets.token_urlsafe(32)

    def _calculate_expiration_time(self) -> datetime:
        """
        Вычисляет время истечения токена.
        """
        return datetime.utcnow() + timedelta(minutes=self.TOKEN_TTL_MINUTES)

    def _build_reset_url(self, token: str) -> str:
        """
        Формирует URL для восстановления пароля.
        """
        return f"{self._base_reset_url}?token={token}"


# =========================
# Инициализация БД
# =========================

def init_database() -> None:
    """
    Создаёт таблицы в базе данных.
    """
    Base.metadata.create_all(bind=engine)


# =========================
# Пример использования
# =========================

def example_usage() -> None:
    """
    Демонстрация работы PasswordResetManager.
    """
    db: Session = SessionLocal()

    user = User(email="user@example.com")
    db.add(user)
    db.commit()
    db.refresh(user)

    repository = PasswordResetRepository(db=db)
    manager = PasswordResetManager(
        repository=repository,
        base_reset_url="https://example.com/reset-password",
    )

    reset_link = manager.create_reset_link(user.email)
    print(f"Password reset link: {reset_link}")

    db.close()
