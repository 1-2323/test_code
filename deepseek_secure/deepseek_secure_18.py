from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import time
import sqlite3
from contextlib import contextmanager
import threading
import hashlib

@dataclass
class RateLimit:
    """Конфигурация лимита."""
    requests: int  # Количество запросов
    period: int    # Период в секундах
    block_duration: int = 60  # Блокировка при превышении

class RateLimiter:
    """Система ограничения запросов."""
    
    def __init__(self, db_path: str = "rate_limits.db"):
        self.db_path = db_path
        self._init_database()
        self.lock = threading.RLock()
    
    def _init_database(self):
        """Инициализация БД."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    key TEXT,
                    period_start INTEGER,
                    count INTEGER DEFAULT 0,
                    blocked_until INTEGER,
                    PRIMARY KEY (key, period_start)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_key ON rate_limits(key)")
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _get_period_start(self, period: int) -> int:
        """Получение начала периода."""
        current_time = int(time.time())
        return (current_time // period) * period
    
    def _cleanup_old(self, conn: sqlite3.Connection):
        """Очистка старых записей."""
        cursor = conn.cursor()
        cutoff = int(time.time()) - 86400  # 24 часа
        cursor.execute(
            "DELETE FROM rate_limits WHERE period_start < ?",
            (cutoff,)
        )
    
    def check_limit(self, key: str, limit: RateLimit) -> Tuple[bool, Dict[str, Any]]:
        """
        Проверка лимита.
        
        Returns:
            (разрешено, информация о лимите)
        """
        with self.lock, self._get_connection() as conn:
            cursor = conn.cursor()
            period_start = self._get_period_start(limit.period)
            
            # Проверяем блокировку
            cursor.execute("""
                SELECT blocked_until FROM rate_limits 
                WHERE key = ? AND period_start = ?
            """, (key, period_start))
            
            row = cursor.fetchone()
            if row and row['blocked_until']:
                if time.time() < row['blocked_until']:
                    return False, {
                        "blocked": True,
                        "blocked_until": row['blocked_until'],
                        "retry_after": int(row['blocked_until'] - time.time())
                    }
                else:
                    # Снимаем блокировку
                    cursor.execute("""
                        UPDATE rate_limits 
                        SET blocked_until = NULL 
                        WHERE key = ? AND period_start = ?
                    """, (key, period_start))
            
            # Получаем текущий счетчик
            cursor.execute("""
                SELECT count FROM rate_limits 
                WHERE key = ? AND period_start = ?
            """, (key, period_start))
            
            row = cursor.fetchone()
            current_count = row['count'] if row else 0
            
            # Проверяем лимит
            if current_count >= limit.requests:
                # Устанавливаем блокировку
                blocked_until = int(time.time()) + limit.block_duration
                cursor.execute("""
                    INSERT OR REPLACE INTO rate_limits 
                    (key, period_start, count, blocked_until)
                    VALUES (?, ?, ?, ?)
                """, (key, period_start, current_count, blocked_until))
                conn.commit()
                
                return False, {
                    "blocked": True,
                    "blocked_until": blocked_until,
                    "retry_after": limit.block_duration,
                    "limit_exceeded": True
                }
            
            # Увеличиваем счетчик
            new_count = current_count + 1
            cursor.execute("""
                INSERT OR REPLACE INTO rate_limits 
                (key, period_start, count, blocked_until)
                VALUES (?, ?, ?, ?)
            """, (key, period_start, new_count, None))
            
            # Очистка старых записей
            self._cleanup_old(conn)
            
            conn.commit()
            
            return True, {
                "allowed": True,
                "remaining": max(0, limit.requests - new_count),
                "reset_time": period_start + limit.period,
                "current": new_count,
                "limit": limit.requests
            }
    
    def get_stats(self, key: str) -> Dict[str, Any]:
        """Получение статистики по ключу."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SUM(count) as total_requests,
                       COUNT(DISTINCT period_start) as periods
                FROM rate_limits 
                WHERE key = ?
            """, (key,))
            
            row = cursor.fetchone()
            return {
                "total_requests": row['total_requests'] or 0,
                "periods_count": row['periods'] or 0
            }
    
    def reset_limit(self, key: str) -> bool:
        """Сброс лимита для ключа."""
        with self.lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM rate_limits WHERE key = ?",
                (key,)
            )
            conn.commit()
            return cursor.rowcount > 0

class RateLimitManager:
    """Менеджер лимитов."""
    
    def __init__(self, limiter: Optional[RateLimiter] = None):
        self.limiter = limiter or RateLimiter()
        self.limits: Dict[str, RateLimit] = {}
    
    def add_limit(self, name: str, requests: int, 
                  period: int, block_duration: int = 60):
        """Добавление конфигурации лимита."""
        self.limits[name] = RateLimit(
            requests=requests,
            period=period,
            block_duration=block_duration
        )
    
    def check(self, limit_name: str, identifier: str) -> Tuple[bool, Dict[str, Any]]:
        """Проверка лимита."""
        if limit_name not in self.limits:
            raise ValueError(f"Limit '{limit_name}' not found")
        
        limit = self.limits[limit_name]
        return self.limiter.check_limit(identifier, limit)
    
    def middleware(self, limit_name: str, 
                   get_identifier: Callable = lambda: "default"):
        """Декоратор для лимитирования."""
        def decorator(func):
            def wrapper(*args, **kwargs):
                identifier = get_identifier()
                allowed, info = self.check(limit_name, identifier)
                
                if not allowed:
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "error": "Rate limit exceeded",
                            "retry_after": info.get("retry_after", 60),
                            "limit": limit_name
                        }
                    )
                
                return func(*args, **kwargs)
            return wrapper
        return decorator