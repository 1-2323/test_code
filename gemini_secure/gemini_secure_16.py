import secrets
import hashlib
import time
from typing import Dict, Optional, Final
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class RecoverySession:
    """Модель временной сессии восстановления аккаунта."""
    user_id: int
    secret_question_passed: bool = False
    phone_code_hash: Optional[str] = None
    code_expires_at: Optional[datetime] = None
    attempts: int = 0
    is_fully_verified: bool = False


class AccountRecoveryManager:
    """
    Сервис многофакторного восстановления (MFA), обеспечивающий защиту 
    от перебора и проверку целостности этапов.
    """

    # Константы безопасности
    MAX_ATTEMPTS: Final[int] = 3
    CODE_LIFETIME_SECONDS: Final[int] = 300  # 5 минут
    SESSION_LIFETIME_MINUTES: Final[int] = 15

    def __init__(self) -> None:
        # Имитация БД (user_id -> данные)
        self._user_db: Dict[int, Dict] = {
            1: {
                "phone": "+79001234567",
                "secret_answer_hash": hashlib.sha256(b"barsik").hexdigest(),
                "password_hash": "old_hash"
            }
        }
        # Имитация кэша сессий (session_token -> RecoverySession)
        self._active_sessions: Dict[str, RecoverySession] = {}

    def _get_hash(self, data: str) -> str:
        """Вспомогательный метод для хеширования."""
        return hashlib.sha256(data.lower().strip().encode()).hexdigest()

    def start_recovery(self, user_id: int, secret_answer: str) -> str:
        """
        Первый этап: проверка секретного вопроса.
        Возвращает токен сессии при успехе.
        """
        user = self._user_db.get(user_id)
        if not user:
            raise ValueError("Invalid user identifier.")

        # Безопасное сравнение ответов
        provided_hash = self._get_hash(secret_answer)
        if not secrets.compare_digest(provided_hash, user["secret_answer_hash"]):
            raise PermissionError("Security answer is incorrect.")

        # Создание сессии
        session_token = secrets.token_urlsafe(32)
        self._active_sessions[session_token] = RecoverySession(
            user_id=user_id,
            secret_question_passed=True
        )
        return session_token

    def send_phone_code(self, session_token: str) -> None:
        """Второй этап: генерация и отправка SMS-кода."""
        session = self._active_sessions.get(session_token)
        if not session or not session.secret_question_passed:
            raise PermissionError("Initial verification not completed.")

        # Генерация 6-значного числового кода
        raw_code = "".join(secrets.choice("0123456789") for _ in range(6))
        
        # Сохранение хеша кода и времени истечения
        session.phone_code_hash = self._get_hash(raw_code)
        session.code_expires_at = datetime.now() + timedelta(seconds=self.CODE_LIFETIME_SECONDS)
        session.attempts = 0

        # Имитация отправки SMS
        print(f"[SMS GATEWAY] Code for User {session.user_id}: {raw_code}")

    def verify_phone_code(self, session_token: str, code: str) -> bool:
        """Третий этап: проверка кода из SMS с лимитом попыток."""
        session = self._active_sessions.get(session_token)
        if not session or not session.phone_code_hash:
            raise PermissionError("Recovery session or code not found.")

        # Проверка лимита попыток и времени жизни
        if session.attempts >= self.MAX_ATTEMPTS:
            del self._active_sessions[session_token]
            raise PermissionError("Too many attempts. Session terminated.")

        if datetime.now() > session.code_expires_at:
            raise TimeoutError("Code has expired.")

        session.attempts += 1
        provided_hash = self._get_hash(code)

        if secrets.compare_digest(provided_hash, session.phone_code_hash):
            session.is_fully_verified = True
            return True
        
        return False

    def reset_password(self, session_token: str, new_password: str) -> None:
        """Финальный этап: смена пароля после полной проверки MFA."""
        session = self._active_sessions.get(session_token)
        if not session or not session.is_fully_verified:
            raise PermissionError("Full MFA verification required to reset password.")

        # Обновление "базы данных"
        user = self._user_db[session.user_id]
        user["password_hash"] = hashlib.sha256(new_password.encode()).hexdigest()

        # Уничтожение сессии после использования (One-time use)
        del self._active_sessions[session_token]

    def cleanup_sessions(self) -> None:
        """Очистка старых сессий по тайм-ауту."""
        now = datetime.now()
        expired = [
            k for k, v in self._active_sessions.items() 
            if (v.code_expires_at and now > v.code_expires_at)
        ]
        for k in expired:
            del self._active_sessions[k]