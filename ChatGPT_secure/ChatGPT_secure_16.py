import hashlib
import hmac
import secrets
import time
from typing import Dict, Optional

from sqlalchemy import Column, Integer, String, Float, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from passlib.context import CryptContext


# =========================
# НАСТРОЙКИ БЕЗОПАСНОСТИ
# =========================

MAX_SECRET_ANSWER_ATTEMPTS = 3
MAX_CODE_ATTEMPTS = 3
CODE_TTL_SECONDS = 300  # 5 минут

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

Base = declarative_base()


# =========================
# МОДЕЛИ БД
# =========================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    phone = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    secret_answer_hash = Column(String, nullable=False)


class PasswordResetState(Base):
    __tablename__ = "password_reset_state"

    user_id = Column(Integer, primary_key=True)
    secret_attempts = Column(Integer, default=0)
    code_attempts = Column(Integer, default=0)
    verification_code_hash = Column(String, nullable=True)
    code_expires_at = Column(Float, nullable=True)


# =========================
# УТИЛИТЫ
# =========================

def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def secure_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


# =========================
# СЕРВИС ОТПРАВКИ SMS (МОК)
# =========================

class SmsGateway:
    @staticmethod
    def send_code(phone: str, code: str) -> None:
        # В реальности — интеграция с SMS-провайдером
        pass


# =========================
# СЕРВИС ВОССТАНОВЛЕНИЯ
# =========================

class AccountRecoveryService:
    """
    Многофакторный процесс восстановления аккаунта.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def verify_secret_answer(self, user: User, answer: str) -> None:
        state = self._get_or_create_state(user.id)

        if state.secret_attempts >= MAX_SECRET_ANSWER_ATTEMPTS:
            raise PermissionError("Превышено количество попыток")

        if not secure_compare(
            hash_value(answer),
            user.secret_answer_hash,
        ):
            state.secret_attempts += 1
            self._db.commit()
            raise PermissionError("Неверный ответ")

        state.secret_attempts = MAX_SECRET_ANSWER_ATTEMPTS
        self._generate_and_send_code(user, state)

    def verify_code(self, user: User, code: str) -> None:
        state = self._get_or_create_state(user.id)

        if state.code_attempts >= MAX_CODE_ATTEMPTS:
            raise PermissionError("Код заблокирован")

        if not state.verification_code_hash:
            raise PermissionError("Код не запрошен")

        if time.time() > (state.code_expires_at or 0):
            raise PermissionError("Код истёк")

        if not secure_compare(
            hash_value(code),
            state.verification_code_hash,
        ):
            state.code_attempts += 1
            self._db.commit()
            raise PermissionError("Неверный код")

        state.code_attempts = MAX_CODE_ATTEMPTS
        self._db.commit()

    def reset_password(self, user: User, new_password: str) -> None:
        state = self._get_or_create_state(user.id)

        if state.code_attempts < MAX_CODE_ATTEMPTS:
            raise PermissionError("Верификация не завершена")

        user.password_hash = hash_password(new_password)
        self._db.delete(state)
        self._db.commit()

    def _generate_and_send_code(self, user: User, state: PasswordResetState) -> None:
        code = f"{secrets.randbelow(1_000_000):06d}"

        state.verification_code_hash = hash_value(code)
        state.code_expires_at = time.time() + CODE_TTL_SECONDS
        state.code_attempts = 0

        self._db.commit()
        SmsGateway.send_code(user.phone, code)

    def _get_or_create_state(self, user_id: int) -> PasswordResetState:
        state = self._db.get(PasswordResetState, user_id)
        if not state:
            state = PasswordResetState(user_id=user_id)
            self._db.add(state)
            self._db.commit()
        return state


# =========================
# ИНИЦИАЛИЗАЦИЯ БД
# =========================

engine = create_engine("sqlite:///:memory:")
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(engine)
