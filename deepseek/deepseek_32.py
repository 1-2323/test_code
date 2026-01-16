import secrets
import time
from typing import Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import redis
import hashlib


@dataclass
class PasswordResetConfig:
    """Конфигурация сброса пароля"""
    token_timeout: int = 3600  # 1 час в секундах
    token_length: int = 32
    min_password_length: int = 8


class PasswordResetService:
    """Сервис сброса пароля по токену"""
    
    def __init__(self, redis_client: redis.Redis, config: Optional[PasswordResetConfig] = None):
        """
        Инициализация сервиса сброса пароля.
        
        Args:
            redis_client: Клиент Redis для хранения токенов
            config: Конфигурация сброса пароля (опционально)
        """
        self.redis = redis_client
        self.config = config or PasswordResetConfig()
    
    def _generate_token(self) -> str:
        """Генерация безопасного токена"""
        return secrets.token_urlsafe(self.config.token_length)
    
    def _get_token_key(self, token: str) -> str:
        """Генерация ключа для хранения токена в Redis"""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return f"pwd_reset:{token_hash}"
    
    def create_reset_token(self, user_id: str, email: str) -> Tuple[str, datetime]:
        """
        Создание токена для сброса пароля.
        
        Args:
            user_id: Идентификатор пользователя
            email: Email пользователя
            
        Returns:
            Кортеж (токен, время истечения)
        """
        token = self._generate_token()
        token_key = self._get_token_key(token)
        expires_at = datetime.utcnow() + timedelta(seconds=self.config.token_timeout)
        
        # Сохраняем токен в Redis с данными пользователя
        token_data = {
            'user_id': user_id,
            'email': email,
            'created_at': int(time.time()),
            'used': '0',
        }
        
        self.redis.hset(token_key, mapping=token_data)
        self.redis.expire(token_key, self.config.token_timeout)
        
        return token, expires_at
    
    def validate_token(self, token: str) -> Tuple[bool, Optional[Dict[str, str]], Optional[str]]:
        """
        Проверка валидности токена сброса пароля.
        
        Args:
            token: Токен для проверки
            
        Returns:
            Кортеж (валидность, данные токена, сообщение об ошибке)
        """
        token_key = self._get_token_key(token)
        
        # Проверяем существование токена
        if not self.redis.exists(token_key):
            return False, None, "Invalid or expired token"
        
        # Получаем данные токена
        token_data = self.redis.hgetall(token_key)
        
        # Проверяем, не использован ли токен
        if token_data.get('used') == '1':
            return False, None, "Token has already been used"
        
        # Проверяем срок действия
        created_at = int(token_data.get('created_at', 0))
        current_time = int(time.time())
        
        if current_time - created_at > self.config.token_timeout:
            return False, None, "Token has expired"
        
        return True, token_data, None
    
    def _validate_password(self, password: str) -> Tuple[bool, Optional[str]]:
        """
        Валидация нового пароля.
        
        Args:
            password: Новый пароль
            
        Returns:
            Кортеж (валидность, сообщение об ошибке)
        """
        if len(password) < self.config.min_password_length:
            return False, f"Password must be at least {self.config.min_password_length} characters long"
        
        # Дополнительные проверки можно добавить здесь
        # (наличие цифр, специальных символов и т.д.)
        
        return True, None
    
    def _hash_password(self, password: str) -> str:
        """Хеширование пароля"""
        # В реальном приложении используйте bcrypt или аналоги
        return hashlib.sha256(password.encode()).hexdigest()
    
    def reset_password(self, token: str, new_password: str) -> Tuple[bool, Optional[str]]:
        """
        Сброс пароля по токену.
        
        Args:
            token: Токен сброса пароля
            new_password: Новый пароль
            
        Returns:
            Кортеж (успешность, сообщение об ошибке)
        """
        # Проверяем валидность токена
        is_valid, token_data, error_message = self.validate_token(token)
        
        if not is_valid:
            return False, error_message
        
        # Валидируем новый пароль
        is_password_valid, password_error = self._validate_password(new_password)
        
        if not is_password_valid:
            return False, password_error
        
        # Получаем данные пользователя из токена
        user_id = token_data['user_id']
        
        # Хешируем новый пароль
        hashed_password = self._hash_password(new_password)
        
        # Здесь должна быть реальная логика обновления пароля в БД
        try:
            self._update_user_password_in_db(user_id, hashed_password)
        except Exception as e:
            return False, f"Failed to update password: {str(e)}"
        
        # Помечаем токен как использованный
        token_key = self._get_token_key(token)
        self.redis.hset(token_key, 'used', '1')
        
        # Удаляем токен (или оставляем на короткое время для аудита)
        self.redis.expire(token_key, 300)  # Удаляем через 5 минут
        
        return True, "Password has been successfully reset"
    
    def _update_user_password_in_db(self, user_id: str, hashed_password: str) -> None:
        """
        Обновление пароля пользователя в базе данных.
        
        Args:
            user_id: Идентификатор пользователя
            hashed_password: Хешированный пароль
        """
        # Реализуйте обновление пароля в вашей БД
        # Это пример, замените на реальную логику
        print(f"Updating password for user {user_id}")
        # В реальном приложении: update users set password_hash = ? where id = ?