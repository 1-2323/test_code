import re
from typing import Optional

from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, validator


# =========================
# Конфигурация БД
# =========================

DATABASE_URL: str = "sqlite:///./users.db"

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
# SQLAlchemy-модель
# =========================

class User(Base):
    """
    ORM-модель пользователя.
    """
    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True, index=True)
    email: str = Column(String, unique=True, index=True, nullable=False)
    hashed_password: str = Column(String, nullable=False)


# =========================
# Pydantic-модель ввода
# =========================

class UserCreate(BaseModel):
    """
    Модель данных для регистрации пользователя.
    """
    email: EmailStr
    password: str

    @validator("password")
    def validate_password_strength(cls, value: str) -> str:
        """
        Проверяет сложность пароля.
        Требования:
        - минимум 8 символов
        - минимум 1 цифра
        - минимум 1 буква в верхнем регистре
        """
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")

        if not re.search(r"[A-Z]", value):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"\d", value):
            raise ValueError("Password must contain at least one digit")

        return value


# =========================
# Хеширование паролей
# =========================

class PasswordHasher:
    """
    Сервис для хеширования и проверки паролей.
    """

    def __init__(self) -> None:
        self._context: CryptContext = CryptContext(
            schemes=["bcrypt"],
            deprecated="auto",
        )

    def hash(self, password: str) -> str:
        """
        Хеширует пароль.
        """
        return self._context.hash(password)

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """
        Проверяет пароль.
        """
        return self._context.verify(plain_password, hashed_password)


# =========================
# Репозиторий пользователей
# =========================

class UserRepository:
    """
    Репозиторий для работы с пользователями.
    """

    def __init__(self, db: Session) -> None:
        self._db: Session = db

    def get_by_email(self, email: str) -> Optional[User]:
        """
        Возвращает пользователя по email.
        """
        return self._db.query(User).filter(User.email == email).first()

    def create(self, email: str, hashed_password: str) -> User:
        """
        Создаёт нового пользователя.
        """
        user = User(
            email=email,
            hashed_password=hashed_password,
        )
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        return user


# =========================
# Сервис регистрации
# =========================

class UserRegistrationFlow:
    """
    Сервис, управляющий процессом регистрации пользователя.
    """

    def __init__(
        self,
        repository: UserRepository,
        password_hasher: PasswordHasher,
    ) -> None:
        self._repository: UserRepository = repository
        self._password_hasher: PasswordHasher = password_hasher

    def register(self, data: UserCreate) -> User:
        """
        Регистрирует нового пользователя.

        Алгоритм:
        1. Проверка, что email не занят
        2. Хеширование пароля
        3. Сохранение пользователя в БД
        """
        existing_user: Optional[User] = self._repository.get_by_email(data.email)

        if existing_user is not None:
            raise ValueError("User with this email already exists")

        hashed_password: str = self._password_hasher.hash(data.password)

        return self._repository.create(
            email=data.email,
            hashed_password=hashed_password,
        )


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

def register_user_example() -> None:
    """
    Демонстрация работы сервиса регистрации.
    """
    db: Session = SessionLocal()
    repository = UserRepository(db=db)
    hasher = PasswordHasher()
    registration_flow = UserRegistrationFlow(
        repository=repository,
        password_hasher=hasher,
    )

    user_data = UserCreate(
        email="user@example.com",
        password="StrongPass1",
    )

    user = registration_flow.register(user_data)
    print(f"User registered with ID: {user.id}")

    db.close()
