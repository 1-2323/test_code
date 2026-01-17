import re
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    Session,
)
from sqlalchemy.exc import IntegrityError

from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, ConfigDict


# =========================
# НАСТРОЙКИ БЕЗОПАСНОСТИ
# =========================

PASSWORD_CONTEXT = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


# =========================
# SQLALCHEMY МОДЕЛИ
# =========================

Base = declarative_base()


class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)


# =========================
# Pydantic СХЕМЫ
# =========================

class UserRegistrationRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    model_config = ConfigDict(extra="forbid")


class UserResponse(BaseModel):
    id: int
    email: EmailStr


# =========================
# ИСКЛЮЧЕНИЯ
# =========================

class RegistrationError(Exception):
    pass


# =========================
# СЕРВИС РЕГИСТРАЦИИ
# =========================

class UserRegistrationFlow:
    """
    Сервис регистрации пользователей.
    """

    PASSWORD_PATTERN = re.compile(
        r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z\d@$!%*?&]+$"
    )

    def __init__(self, session: Session) -> None:
        self._session: Session = session

    def register_user(
        self,
        data: UserRegistrationRequest,
    ) -> UserResponse:
        """
        Регистрирует нового пользователя.
        """
        self._validate_password(data.password)

        password_hash: str = self._hash_password(data.password)

        user = UserORM(
            email=data.email,
            password_hash=password_hash,
        )

        try:
            self._session.add(user)
            self._session.commit()
            self._session.refresh(user)
        except IntegrityError as exc:
            self._session.rollback()
            raise RegistrationError("Пользователь с таким email уже существует") from exc

        return UserResponse(
            id=user.id,
            email=user.email,
        )

    def _validate_password(self, password: str) -> None:
        """
        Проверяет сложность пароля.
        """
        if not self.PASSWORD_PATTERN.match(password):
            raise RegistrationError(
                "Пароль должен содержать минимум одну заглавную букву, "
                "одну строчную букву и одну цифру"
            )

    def _hash_password(self, password: str) -> str:
        """
        Хеширует пароль с солью.
        """
        return PASSWORD_CONTEXT.hash(password)


# =========================
# ИНИЦИАЛИЗАЦИЯ БД
# =========================

DATABASE_URL = "sqlite:///users.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)

Base.metadata.create_all(engine)



