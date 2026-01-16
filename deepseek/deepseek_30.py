import redis
import hashlib
import time
from typing import Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class AuthResult(Enum):
    """Результат попытки аутентификации"""
    SUCCESS = "success"
    INVALID_CREDENTIALS = "invalid_credentials"
    ACCOUNT_LOCKED = "account_locked"
    TOO_MANY_ATTEMPTS = "too_many_attempts"


@dataclass
class AuthConfig:
    """Конфигурация аутентификации"""
    max_attempts: int = 5
    lock_timeout: int = 900  # 15 минут в секундах
    attempt_window: int = 300  # 5 минут в секундах


class AuthService:
    """Сервис аутентификации с блокировкой аккаунта"""
    
    def __init__(self, redis_client: redis.Redis, config: Optional[AuthConfig] = None):
        """
        Инициализация сервиса аутентификации.
        
        Args:
            redis_client: Клиент Redis для хранения счетчиков попыток
            config: Конфигурация аутентификации (опционально)
        """
        self.redis = redis_client
        self.config = config or AuthConfig()
    
    def _get_attempt_key(self, username: str) -> str:
        """Генерация ключа для хранения счетчика попыток"""
        return f"auth:attempts:{username}"
    
    def _get_lock_key(self, username: str) -> str:
        """Генерация ключа для блокировки аккаунта"""
        return f"auth:lock:{username}"
    
    def _hash_password(self, password: str) -> str:
        """Хеширование пароля (упрощенный пример, в реальности используйте bcrypt/scrypt)"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def is_account_locked(self, username: str) -> bool:
        """
        Проверка, заблокирован ли аккаунт.
        
        Args:
            username: Имя пользователя
            
        Returns:
            True если аккаунт заблокирован
        """
        lock_key = self._get_lock_key(username)
        return bool(self.redis.get(lock_key))
    
    def increment_attempt_counter(self, username: str) -> int:
        """
        Увеличение счетчика неудачных попыток.
        
        Args:
            username: Имя пользователя
            
        Returns:
            Текущее количество попыток
        """
        attempt_key = self._get_attempt_key(username)
        
        # Используем pipeline для атомарных операций
        pipe = self.redis.pipeline()
        pipe.incr(attempt_key)
        pipe.expire(attempt_key, self.config.attempt_window)
        results = pipe.execute()
        
        current_attempts = results[0]
        
        # Если превышен лимит - блокируем аккаунт
        if current_attempts >= self.config.max_attempts:
            lock_key = self._get_lock_key(username)
            self.redis.setex(lock_key, self.config.lock_timeout, "locked")
        
        return current_attempts
    
    def reset_attempt_counter(self, username: str) -> None:
        """
        Сброс счетчика неудачных попыток.
        
        Args:
            username: Имя пользователя
        """
        attempt_key = self._get_attempt_key(username)
        lock_key = self._get_lock_key(username)
        
        pipe = self.redis.pipeline()
        pipe.delete(attempt_key)
        pipe.delete(lock_key)
        pipe.execute()
    
    def authenticate(self, username: str, password: str) -> Tuple[AuthResult, Optional[str]]:
        """
        Аутентификация пользователя.
        
        Args:
            username: Имя пользователя
            password: Пароль
            
        Returns:
            Кортеж (результат аутентификации, сообщение об ошибке)
        """
        # Проверяем блокировку аккаунта
        if self.is_account_locked(username):
            return AuthResult.ACCOUNT_LOCKED, "Account is temporarily locked"
        
        # Здесь должна быть реальная проверка пароля из БД
        # Для примера используем фиктивные данные
        stored_password_hash = self._get_user_password_hash(username)  # Реализуйте этот метод
        
        hashed_password = self._hash_password(password)
        
        if hashed_password == stored_password_hash:
            # Успешная аутентификация - сбрасываем счетчик
            self.reset_attempt_counter(username)
            return AuthResult.SUCCESS, None
        else:
            # Неудачная попытка - увеличиваем счетчик
            attempts = self.increment_attempt_counter(username)
            
            if attempts >= self.config.max_attempts:
                return AuthResult.TOO_MANY_ATTEMPTS, "Too many failed attempts"
            
            remaining = self.config.max_attempts - attempts
            return AuthResult.INVALID_CREDENTIALS, f"Invalid credentials. {remaining} attempts remaining"
    
    def _get_user_password_hash(self, username: str) -> str:
        """
        Получение хеша пароля пользователя из БД.
        В реальном приложении этот метод должен обращаться к базе данных.
        """
        # Заглушка для примера
        # Реализуйте получение реального хеша из БД
        return "example_hash"