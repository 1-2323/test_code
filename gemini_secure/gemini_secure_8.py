import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Final, Dict
from dataclasses import dataclass


@dataclass
class ResetToken:
    """Модель данных токена восстановления."""
    user_id: int
    token_hash: str
    expires_at: datetime
    is_active: bool


class PasswordResetManager:
    """
    Сервис управления восстановлением паролей.
    Обеспечивает безопасность через криптостойкие токены и ограничение времени жизни ссылок.
    """

    # Константы безопасности
    TOKEN_EXPIRATION_MINUTES: Final[int] = 15
    BASE_URL: Final[str] = "https://app.example.com/reset-password"

    def __init__(self) -> None:
        """Инициализация сервиса с имитацией базы данных."""
        # В реальной системе это была бы таблица в БД
        self._db_tokens: Dict[str, ResetToken] = {}

    def _hash_token(self, token: str) -> str:
        """Создает SHA-256 хеш токена для безопасного хранения."""
        return hashlib.sha256(token.encode()).hexdigest()

    def generate_reset_link(self, user_id: int) -> str:
        """
        Генерирует уникальный токен и формирует URL для пользователя.
        
        :param user_id: Идентификатор пользователя.
        :return: Полный URL для сброса пароля.
        """
        # Использование secrets для криптографически стойкой генерации (PEP 506)
        raw_token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(raw_token)
        
        # Установка времени истечения
        expiration_date = datetime.now() + timedelta(minutes=self.TOKEN_EXPIRATION_MINUTES)

        # Сохранение метаданных токена
        self._db_tokens[token_hash] = ResetToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expiration_date,
            is_active=True
        )

        return f"{self.BASE_URL}?token={raw_token}"

    def validate_and_use_token(self, raw_token: str) -> Optional[int]:
        """
        Проверяет валидность токена и деактивирует его в случае успеха.
        
        :param raw_token: Токен из URL-адреса.
        :return: ID пользователя, если токен валиден, иначе None.
        """
        token_hash = self._hash_token(raw_token)
        token_data = self._db_tokens.get(token_hash)

        if not token_data:
            return None

        # Проверка: не был ли токен использован ранее
        if not token_data.is_active:
            return None

        # Проверка: не истекло ли время жизни токена
        if datetime.now() > token_data.expires_at:
            token_data.is_active = False  # Деактивируем просроченный токен
            return None

        # Одноразовое использование: деактивируем сразу после успешной проверки
        token_data.is_active = False
        
        return token_data.user_id

    def cleanup_expired_tokens(self) -> int:
        """Удаляет устаревшие токены из хранилища для экономии ресурсов."""
        now = datetime.now()
        initial_count = len(self._db_tokens)
        
        self._db_tokens = {
            h: t for h, t in self._db_tokens.items() 
            if t.expires_at > now and t.is_active
        }
        
        return initial_count - len(self._db_tokens)