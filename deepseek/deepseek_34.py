import time
import hashlib
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
import redis
from user_agents import parse


@dataclass
class SessionMonitorConfig:
    """Конфигурация мониторинга сессий"""
    suspicious_ip_change: bool = True
    suspicious_fingerprint_change: bool = True
    max_concurrent_sessions: int = 3
    session_inactivity_timeout: int = 7200  # 2 часа в секундах


class SessionMonitor:
    """Система мониторинга активных сессий"""
    
    def __init__(self, redis_client: redis.Redis, 
                 session_provider: 'SessionProvider',
                 config: Optional[SessionMonitorConfig] = None):
        """
        Инициализация мониторинга сессий.
        
        Args:
            redis_client: Клиент Redis
            session_provider: Провайдер сессий
            config: Конфигурация мониторинга (опционально)
        """
        self.redis = redis_client
        self.session_provider = session_provider
        self.config = config or SessionMonitorConfig()
    
    def _generate_fingerprint(self, user_agent: str, 
                            accept_language: str,
                            screen_resolution: str,
                            timezone: str) -> str:
        """
        Генерация fingerprint браузера.
        
        Args:
            user_agent: User-Agent браузера
            accept_language: Accept-Language заголовок
            screen_resolution: Разрешение экрана
            timezone: Часовой пояс
            
        Returns:
            Хеш fingerprint
        """
        fingerprint_data = f"{user_agent}:{accept_language}:{screen_resolution}:{timezone}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()
    
    def _get_user_sessions_key(self, user_id: str) -> str:
        """Генерация ключа для хранения активных сессий пользователя"""
        return f"user:sessions:{user_id}"
    
    def track_session_creation(self, user_id: str, session_id: str, 
                             ip_address: str, user_agent: str,
                             fingerprint_data: Dict[str, str]) -> None:
        """
        Отслеживание создания новой сессии.
        
        Args:
            user_id: Идентификатор пользователя
            session_id: Идентификатор сессии
            ip_address: IP-адрес
            user_agent: User-Agent браузера
            fingerprint_data: Данные для генерации fingerprint
        """
        user_sessions_key = self._get_user_sessions_key(user_id)
        
        # Добавляем сессию в список активных сессий пользователя
        session_data = {
            'session_id': session_id,
            'ip_address': ip_address,
            'user_agent': user_agent,
            'created_at': int(time.time()),
            'last_activity': int(time.time()),
        }
        
        # Сохраняем данные сессии
        self.redis.hset(f"{user_sessions_key}:{session_id}", mapping=session_data)
        
        # Добавляем сессию в список активных сессий пользователя
        self.redis.sadd(user_sessions_key, session_id)
        
        # Устанавливаем время жизни
        self.redis.expire(user_sessions_key, self.config.session_inactivity_timeout)
        self.redis.expire(f"{user_sessions_key}:{session_id}", 
                         self.config.session_inactivity_timeout)
    
    def check_session_security(self, user_id: str, session_id: str,
                             current_ip: str, current_fingerprint: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Проверка безопасности сессии при каждом запросе.
        
        Args:
            user_id: Идентификатор пользователя
            session_id: Идентификатор сессии
            current_ip: Текущий IP-адрес
            current_fingerprint: Текущий fingerprint
            
        Returns:
            Кортеж (безопасность сессии, детали проверки)
        """
        security_check = {
            'is_secure': True,
            'warnings': [],
            'alerts': [],
            'recommendations': []
        }
        
        # Получаем данные сессии
        session_data = self.session_provider.get_session(session_id)
        
        if not session_data:
            security_check['is_secure'] = False
            security_check['alerts'].append("Session not found")
            return False, security_check
        
        # Получаем оригинальные данные сессии
        original_ip = session_data.get('ip_address')
        original_fingerprint = session_data.get('fingerprint')
        original_user_agent = session_data.get('user_agent')
        
        # Проверяем IP-адрес
        if self.config.suspicious_ip_change and original_ip and original_ip != current_ip:
            security_check['warnings'].append(f"IP address changed: {original_ip} -> {current_ip}")
            
            # Проверяем, является ли это подозрительным изменением
            if self._is_suspicious_ip_change(original_ip, current_ip):
                security_check['alerts'].append("Suspicious IP address change detected")
                security_check['is_secure'] = False
        
        # Проверяем fingerprint браузера
        if (self.config.suspicious_fingerprint_change and 
            original_fingerprint and 
            original_fingerprint != current_fingerprint):
            security_check['warnings'].append("Browser fingerprint changed")
            
            # Проверяем User-Agent для дополнительной информации
            current_user_agent = session_data.get('current_user_agent', '')
            if original_user_agent != current_user_agent:
                security_check['alerts'].append("User-Agent changed along with fingerprint")
                security_check['is_secure'] = False
        
        # Проверяем количество активных сессий
        active_sessions = self.get_active_sessions(user_id)
        if len(active_sessions) > self.config.max_concurrent_sessions:
            security_check['warnings'].append(
                f"Too many active sessions: {len(active_sessions)}"
            )
            security_check['recommendations'].append(
                "Consider terminating unused sessions"
            )
        
        # Обновляем время последней активности
        self._update_session_activity(user_id, session_id)
        
        return security_check['is_secure'], security_check
    
    def _is_suspicious_ip_change(self, original_ip: str, current_ip: str) -> bool:
        """
        Проверка, является ли смена IP-адреса подозрительной.
        
        Args:
            original_ip: Оригинальный IP-адрес
            current_ip: Текущий IP-адрес
            
        Returns:
            True если изменение подозрительное
        """
        # Простая проверка: разные подсети (первые 3 октета)
        # В реальном приложении используйте геолокацию и более сложную логику
        
        original_parts = original_ip.split('.')[:3]
        current_parts = current_ip.split('.')[:3]
        
        return original_parts != current_parts
    
    def _update_session_activity(self, user_id: str, session_id: str) -> None:
        """
        Обновление времени последней активности сессии.
        
        Args:
            user_id: Идентификатор пользователя
            session_id: Идентификатор сессии
        """
        user_sessions_key = self._get_user_sessions_key(user_id)
        session_data_key = f"{user_sessions_key}:{session_id}"
        
        current_time = int(time.time())
        
        if self.redis.exists(session_data_key):
            self.redis.hset(session_data_key, 'last_activity', current_time)
            self.redis.expire(session_data_key, self.config.session_inactivity_timeout)
            self.redis.expire(user_sessions_key, self.config.session_inactivity_timeout)
    
    def get_active_sessions(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Получение всех активных сессий пользователя.
        
        Args:
            user_id: Идентификатор пользователя
            
        Returns:
            Словарь активных сессий
        """
        user_sessions_key = self._get_user_sessions_key(user_id)
        
        # Получаем все идентификаторы сессий
        session_ids = self.redis.smembers(user_sessions_key)
        
        active_sessions = {}
        
        for session_id in session_ids:
            session_id = session_id.decode()
            session_data_key = f"{user_sessions_key}:{session_id}"
            
            # Получаем данные сессии
            session_data = self.redis.hgetall(session_data_key)
            
            if session_data:
                # Конвертируем байтовые строки
                decoded_data = {
                    k.decode(): v.decode() for k, v in session_data.items()
                }