import hashlib
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Optional


# =========================
# Исключения домена
# =========================

class RecoveryError(Exception):
    """Базовое исключение восстановления доступа."""


class InvalidSecretAnswerError(RecoveryError):
    """Неверный ответ на секретный вопрос."""


class InvalidVerificationCodeError(RecoveryError):
    """Неверный или просроченный код подтверждения."""


# =========================
# Модели
# =========================

class User:
    """
    Модель пользователя (упрощённая).
    """
    def __init__(
        self,
        user_id: int,
        secret_answer_hash: str,
        phone: str,
        password_hash: str,
    ) -> None:
        self.user_id: int = user_id
        self.secret_answer_hash: str = secret_answer_hash
        self.phone: str = phone
        self.password_hash: str = password_hash


class VerificationCode:
    """
    Модель одноразового кода подтверждения.
    """
    def __init__(self, code: str, expires_at: datetime) -> None:
        self.code: str = code
        self.expires_at: datetime = expires_at

    def is_valid(self, value: str) -> bool:
        """
        Проверяет корректность и срок действия кода.
        """
        return value == self.code and datetime.utcnow() <= self.expires_at


# =========================
# Репозиторий пользователей
# =========================

class UserRepository:
    """
    Репозиторий пользователей (in-memory).
    """

    def __init__(self) -> None:
        self._users: Dict[int, User] = {}

    def get_by_id(self, user_id: int) -> User:
        return self._users[user_id]

    def save(self, user: User) -> None:
        self._users[user.user_id] = user


# =========================
# Сервисы
# =========================

class PasswordHasher:
    """
    Сервис хеширования паролей.
    """

    @staticmethod
    def hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()


class SmsSender:
    """
    Сервис отправки SMS (имитация).
    """

    @staticmethod
    def send(phone: str, message: str) -> None:
        print(f"[SMS] To {phone}: {message}")


class VerificationCodeManager:
    """
    Управление кодами подтверждения.
    """

    CODE_TTL_MINUTES: int = 5

    def __init__(self) -> None:
        self._codes: Dict[int, VerificationCode] = {}

    def generate_for_user(self, user_id: int) -> str:
        """
        Генерирует и сохраняет код подтверждения.
        """
        code: str = "".join(random.choices(string.digits, k=6))
        expires_at = datetime.utcnow() + timedelta(minutes=self.CODE_TTL_MINUTES)
        self._codes[user_id] = VerificationCode(code, expires_at)
        return code

    def validate(self, user_id: int, code: str) -> None:
        """
        Проверяет код подтверждения.
        """
        stored: Optional[VerificationCode] = self._codes.get(user_id)

        if not stored or not stored.is_valid(code):
            raise InvalidVerificationCodeError()

        del self._codes[user_id]


# =========================
# Основной сервис восстановления
# =========================

class AccountRecoveryService:
    """
    Многофакторный процесс восстановления аккаунта.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        code_manager: VerificationCodeManager,
    ) -> None:
        self._users = user_repository
        self._codes = code_manager

    def verify_secret_answer(self, user_id: int, answer: str) -> None:
        """
        Проверяет ответ на секретный вопрос.
        """
        user = self._users.get_by_id(user_id)
        hashed = PasswordHasher.hash(answer)

        if hashed != user.secret_answer_hash:
            raise InvalidSecretAnswerError()

    def send_verification_code(self, user_id: int) -> None:
        """
        Отправляет код подтверждения на телефон.
        """
        user = self._users.get_by_id(user_id)
        code = self._codes.generate_for_user(user_id)
        SmsSender.send(user.phone, f"Your recovery code: {code}")

    def reset_password(
        self,
        user_id: int,
        verification_code: str,
        new_password: str,
    ) -> None:
        """
        Финальный шаг восстановления — смена пароля.
        """
        self._codes.validate(user_id, verification_code)

        user = self._users.get_by_id(user_id)
        user.password_hash = PasswordHasher.hash(new_password)
        self._users.save(user)
