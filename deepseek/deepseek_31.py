import secrets
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import redis


@dataclass
class SessionConfig:
    """Конфигурация сессии"""
    session_timeout: int = 3600  # 1 час в секундах
    cookie_name: str = "session_id"
    cookie_domain: str = ".example.com"
    cookie_secure: bool = True
    cookie_httponly: bool = True
    cookie_samesite: str = "Lax"


class SessionProvider:
    """Менеджер сессий пользователя"""
    
    def __init__(self, redis_client: redis.Redis, config: Optional[SessionConfig] = None):
        """
        Инициализация менеджера сессий.
        
        Args:
            redis_client: Клиент Redis для хранения сессий
            config: Конфигурация сессий (опционально)
        """
        self.redis = redis_client
        self.config = config or SessionConfig()
    
    def _generate_session_id(self) -> str:
        """Генерация уникального идентификатора сессии"""
        return secrets.token_urlsafe(32)
    
    def _get_session_key(self, session_id: str) -> str:
        """Генерация ключа для хранения сессии в Redis"""
        return f"session:{session_id}"
    
    def create_session(self, user_id: str, user_data: Optional[Dict[str, Any]] = None) -> str:
        """
        Создание новой сессии пользователя.
        
        Args:
            user_id: Идентификатор пользователя
            user_data: Дополнительные данные пользователя
            
        Returns:
            Идентификатор сессии
        """
        session_id = self._generate_session_id()
        session_key = self._get_session_key(session_id)
        
        # Формируем данные сессии
        session_data = {
            'user_id': user_id,
            'created_at': int(time.time()),
            'last_activity': int(time.time()),
            'ip_address': None,  # Будет установлено при первом запросе
            'user_agent': None,  # Будет установлено при первом запросе
            'fingerprint': None,  # Будет установлено при первом запросе
        }
        
        if user_data:
            session_data.update(user_data)
        
        # Сохраняем сессию в Redis
        self.redis.hset(session_key, mapping=session_data)
        self.redis.expire(session_key, self.config.session_timeout)
        
        return session_id
    
    def get_session_cookie_settings(self) -> Dict[str, Any]:
        """
        Получение параметров для установки куки сессии.
        
        Returns:
            Словарь с параметрами куки
        """
        return {
            'key': self.config.cookie_name,
            'value': '',  # Значение будет установлено при создании сессии
            'max_age': self.config.session_timeout,
            'expires': datetime.utcnow() + timedelta(seconds=self.config.session_timeout),
            'domain': self.config.cookie_domain,
            'secure': self.config.cookie_secure,
            'httponly': self.config.cookie_httponly,
            'samesite': self.config.cookie_samesite,
            'path': '/',
        }
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение данных сессии.
        
        Args:
            session_id: Идентификатор сессии
            
        Returns:
            Данные сессии или None если сессия не найдена
        """
        session_key = self._get_session_key(session_id)
        
        # Проверяем существование сессии
        if not self.redis.exists(session_key):
            return None
        
        # Получаем все поля сессии
        session_data = self.redis.hgetall(session_key)
        
        # Обновляем время последней активности
        self.redis.hset(session_key, 'last_activity', int(time.time()))
        self.redis.expire(session_key, self.config.session_timeout)
        
        return session_data
    
    def update_session_metadata(self, session_id: str, ip_address: str, 
                               user_agent: str, fingerprint: str) -> bool:
        """
        Обновление метаданных сессии (IP, User-Agent, Fingerprint).
        
        Args:
            session_id: Идентификатор сессии
            ip_address: IP-адрес пользователя
            user_agent: User-Agent браузера
            fingerprint: Fingerprint браузера
            
        Returns:
            True если сессия обновлена, False если сессия не найдена
        """
        session_key = self._get_session_key(session_id)
        
        if not self.redis.exists(session_key):
            return False
        
        updates = {
            'ip_address': ip_address,
            'user_agent': user_agent,
            'fingerprint': fingerprint,
            'last_activity': int(time.time()),
        }
        
        self.redis.hset(session_key, mapping=updates)
        return True
    
    def invalidate_session(self, session_id: str) -> bool:
        """
        Инвалидация (удаление) сессии.
        
        Args:
            session_id: Идентификатор сессии
            
        Returns:
            True если сессия удалена, False если сессия не найдена
        """
        session_key = self._get_session_key(session_id)
        
        if self.redis.exists(session_key):
            self.redis.delete(session_key)
            return True
        
        return False
    
    def extend_session(self, session_id: str, additional_time: int = 0) -> bool:
        """
        Продление времени жизни сессии.
        
        Args:
            session_id: Идентификатор сессии
            additional_time: Дополнительное время в секундах
            
        Returns:
            True если сессия продлена, False если сессия не найдена
        """
        session_key = self._get_session_key(session_id)
        
        if not self.redis.exists(session_key):
            return False
        
        # Если additional_time = 0, используем стандартный timeout
        new_timeout = additional_time if additional_time > 0 else self.config.session_timeout
        self.redis.expire(session_key, new_timeout)
        
        return True