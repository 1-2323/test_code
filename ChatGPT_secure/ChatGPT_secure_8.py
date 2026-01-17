import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    Session,
)
from sqlalchemy.exc import NoResultFound


# =========================
# SQLALCHEMY BASE
# =========================

Base = declarative_base()


# =========================
# ORM МОДЕЛИ
# =========================

class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)


class PasswordResetTokenORM(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(128), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)


# =========================
# ИСКЛЮЧЕНИЯ
# =========================

class PasswordResetError(Exception):
    pass


class TokenExpiredError(PasswordResetError):
    pass


class TokenAlreadyUsedError(PasswordResetError):
    pass


class TokenNotFoundError(PasswordResetError):
    pass


# =========================
# СЕРВИС ВОССТАНОВЛЕНИЯ ПАРОЛЯ
# =========================

class PasswordResetManager:
    """
    Сервис управления восстановлением доступа пользователя.
    """

    TOKEN_TTL_MINUTES = 15
    TOKEN_LENGTH_BYTES = 32

    def __init__(self, session: Session, base_reset_url: str) -> None:
        self._session: Session = session
        self._base_reset_url: str = base_reset_url.rstrip("/")

    def create_reset_token(self, user: UserORM) -> str:
        """
        Генерирует токен восстановления, сохраняет его в БД
        и возвращает URL для отправки пользователю.
        """
        token: str = self._generate_secure_token()
        now: datetime = datetime.utcnow()

        reset_token = PasswordResetTokenORM(
            user_id=user.id,
            token=token,
            created_at=now,
            expires_at=now + timedelta(minutes=self.TOKEN_TTL_MINUTES),
            is_used=False,
        )

        self._session.add(reset_token)
        self._session.commit()

        return self._build_reset_url(token)

    def validate_and_consume_token(self, token: str) -> int:
        """
        Проверяет валидность токена и деактивирует его
        после успешного использования.

        :param token: токен восстановления
        :return: ID пользователя
        """
        reset_token = self._get_token(token)

        self._validate_token_state(reset_token)

        reset_token.is_used = True
        self._session.commit()

        return reset_token.user_id

    def _generate_secure_token(self) -> str:
        """
        Генерирует криптографически стойкий токен.
        """
        return secrets.token_urlsafe(self.TOKEN_LENGTH_BYTES)

    def _build_reset_url(self, token: str) -> str:
        """
        Формирует URL восстановления пароля.
        """
        return f"{self._base_reset_url}?token={token}"

    def _get_token(self, token: str) -> PasswordResetTokenORM:
        """
        Получает токен восстановления из БД.
        """
        statement = select(PasswordResetTokenORM).where(
            PasswordResetTokenORM.token == token
        )

        result = self._session.execute(statement).scalar_one_or_none()

        if result is None:
            raise TokenNotFoundError("Токен восстановления не найден")

        return result

    def _validate_token_state(self, reset_token: PasswordResetTokenORM) -> None:
        """
        Проверяет срок действия и состояние токена.
        """
        now: datetime = datetime.utcnow()

        if reset_token.is_used:
            raise TokenAlreadyUsedError("Токен уже был использован")

        if reset_token.expires_at < now:
            raise TokenExpiredError("Срок действия токена истёк")


# =========================
# ИНИЦИАЛИЗАЦИЯ БД
# =========================

DATABASE_URL = "sqlite:///password_reset.db"

engine = create_engine(
    DATABASE_URL,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)

Base.metadata.create_all(engine)
