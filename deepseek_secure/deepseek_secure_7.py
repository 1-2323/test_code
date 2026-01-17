import time
import pickle
from typing import Any, Optional, Dict, Union
from datetime import datetime, timedelta
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
import threading
from pathlib import Path
import sqlite3
from contextlib import contextmanager


class CacheBackend(str, Enum):
    """Типы хранилищ для кеша."""
    MEMORY = "memory"
    REDIS = "redis"
    FILESYSTEM = "filesystem"
    DATABASE = "database"


@dataclass
class CacheItem:
    """Элемент кеша с метаданными."""
    key: str
    value: Any
    created_at: float
    expires_at: Optional[float] = None
    hits: int = 0
    size: int = 0
    
    def is_expired(self) -> bool:
        """Проверка истечения срока жизни."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def time_to_live(self) -> Optional[float]:
        """Оставшееся время жизни в секундах."""
        if self.expires_at is None:
            return None
        ttl = self.expires_at - time.time()
        return max(0, ttl) if ttl > 0 else 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'key': self.key,
            'value': self.value,
            'created_at': self.created_at,
            'expires_at': self.expires_at,
            'hits': self.hits,
            'size': self.size
        }


class CacheKeyBuilder:
    """Построитель ключей для кеша."""
    
    @staticmethod
    def build_key(*args, **kwargs) -> str:
        """
        Создание ключа кеша на основе аргументов функции.
        
        Args:
            *args: Позиционные аргументы
            **kwargs: Именованные аргументы
            
        Returns:
            Уникальный ключ кеша
        """
        # Игнорируем self для методов
        if args and hasattr(args[0], '__class__'):
            args = args[1:]
        
        # Создаем строковое представление
        key_parts = []
        
        # Добавляем позиционные аргументы
        for i, arg in enumerate(args):
            key_parts.append(f"arg_{i}:{repr(arg)}")
        
        # Добавляем именованные аргументы
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}:{repr(v)}")
        
        # Объединяем и хешируем
        key_string = "|".join(key_parts)
        
        # Используем SHA256 для создания компактного ключа
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]
    
    @staticmethod
    def build_namespaced_key(namespace: str, key: str) -> str:
        """
        Создание ключа с пространством имен.
        
        Args:
            namespace: Пространство имен
            key: Базовый ключ
            
        Returns:
            Ключ с namespace
        """
        return f"{namespace}:{key}"


class BaseCacheBackend:
    """Базовый класс для бэкендов кеша."""
    
    def get(self, key: str) -> Optional[CacheItem]:
        """Получение элемента из кеша."""
        raise NotImplementedError
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Сохранение элемента в кеш."""
        raise NotImplementedError
    
    def delete(self, key: str) -> bool:
        """Удаление элемента из кеша."""
        raise NotImplementedError
    
    def exists(self, key: str) -> bool:
        """Проверка существования ключа."""
        raise NotImplementedError
    
    def clear(self) -> int:
        """Очистка всего кеша."""
        raise NotImplementedError
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики кеша."""
        raise NotImplementedError


class MemoryCacheBackend(BaseCacheBackend):
    """Бэкенд кеша в оперативной памяти."""
    
    def __init__(self, max_size: int = 1000):
        """
        Инициализация кеша в памяти.
        
        Args:
            max_size: Максимальное количество элементов
        """
        self._cache: Dict[str, CacheItem] = {}
        self.max_size = max_size
        self.lock = threading.RLock()  # Для потокобезопасности
        self._hits = 0
        self._misses = 0
        self._evictions = 0
    
    def _evict_if_needed(self) -> None:
        """Удаление старых элементов при превышении лимита."""
        if len(self._cache) >= self.max_size:
            with self.lock:
                # Находим самый старый или истекший элемент
                to_evict = None
                oldest_time = float('inf')
                
                for key, item in self._cache.items():
                    if item.is_expired():
                        to_evict = key
                        break
                    if item.created_at < oldest_time:
                        oldest_time = item.created_at
                        to_evict = key
                
                if to_evict:
                    del self._cache[to_evict]
                    self._evictions += 1
    
    def get(self, key: str) -> Optional[CacheItem]:
        """Получение элемента из кеша."""
        with self.lock:
            if key in self._cache:
                item = self._cache[key]
                
                # Проверяем не истек ли срок
                if item.is_expired():
                    del self._cache[key]
                    self._misses += 1
                    return None
                
                # Обновляем статистику использования
                item.hits += 1
                self._hits += 1
                return item
            
            self._misses += 1
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Сохранение элемента в кеш."""
        with self.lock:
            # Удаляем старые элементы если нужно
            self._evict_if_needed()
            
            # Создаем элемент кеша
            created_at = time.time()
            expires_at = created_at + ttl if ttl else None
            
            # Пытаемся определить размер (примерно)
            try:
                size = len(pickle.dumps(value))
            except:
                size = 0
            
            item = CacheItem(
                key=key,
                value=value,
                created_at=created_at,
                expires_at=expires_at,
                size=size
            )
            
            self._cache[key] = item
            return True
    
    def delete(self, key: str) -> bool:
        """Удаление элемента из кеша."""
        with self.lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def exists(self, key: str) -> bool:
        """Проверка существования ключа."""
        with self.lock:
            if key in self._cache:
                item = self._cache[key]
                return not item.is_expired()
            return False
    
    def clear(self) -> int:
        """Очистка всего кеша."""
        with self.lock:
            count = len(self._cache)
            self._cache.clear()
            return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики кеша."""
        with self.lock:
            total_size = sum(item.size for item in self._cache.values())
            expired_count = sum(1 for item in self._cache.values() if item.is_expired())
            
            return {
                'items': len(self._cache),
                'max_size': self.max_size,
                'total_size_bytes': total_size,
                'expired_items': expired_count,
                'hits': self._hits,
                'misses': self._misses,
                'hit_ratio': self._hits / (self._hits + self._misses) if (self._hits + self._misses) > 0 else 0,
                'evictions': self._evictions,
                'backend': 'memory'
            }


class DatabaseCacheBackend(BaseCacheBackend):
    """Бэкенд кеша в SQLite базе данных."""
    
    def __init__(self, db_path: str = "cache.db"):
        """
        Инициализация кеша в БД.
        
        Args:
            db_path: Путь к файлу БД
        """
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_items (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    hits INTEGER DEFAULT 0,
                    size INTEGER DEFAULT 0,
                    namespace TEXT DEFAULT 'default'
                )
            """)
            
            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_expires_at ON cache_items(expires_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_namespace ON cache_items(namespace)")
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для подключения к БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _clean_expired(self):
        """Очистка истекших элементов."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM cache_items WHERE expires_at IS NOT NULL AND expires_at < ?",
                (time.time(),)
            )
            conn.commit()
    
    def get(self, key: str) -> Optional[CacheItem]:
        """Получение элемента из кеша."""
        self._clean_expired()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM cache_items WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            
            if row:
                # Десериализуем значение
                try:
                    value = pickle.loads(row['value'])
                except:
                    value = None
                
                # Обновляем счетчик обращений
                cursor.execute(
                    "UPDATE cache_items SET hits = hits + 1 WHERE key = ?",
                    (key,)
                )
                conn.commit()
                
                return CacheItem(
                    key=row['key'],
                    value=value,
                    created_at=row['created_at'],
                    expires_at=row['expires_at'],
                    hits=row['hits'] + 1,
                    size=row['size']
                )
            
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Сохранение элемента в кеш."""
        try:
            # Сериализуем значение
            value_bytes = pickle.dumps(value)
            size = len(value_bytes)
            
            created_at = time.time()
            expires_at = created_at + ttl if ttl else None
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO cache_items 
                    (key, value, created_at, expires_at, size)
                    VALUES (?, ?, ?, ?, ?)
                """, (key, value_bytes, created_at, expires_at, size))
                
                conn.commit()
                return True
                
        except Exception as e:
            print(f"Error setting cache item: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Удаление элемента из кеша."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM cache_items WHERE key = ?",
                (key,)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def exists(self, key: str) -> bool:
        """Проверка существования ключа."""
        self._clean_expired()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM cache_items WHERE key = ?",
                (key,)
            )
            return cursor.fetchone()['count'] > 0
    
    def clear(self, namespace: Optional[str] = None) -> int:
        """Очистка кеша (опционально по namespace)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if namespace:
                cursor.execute(
                    "DELETE FROM cache_items WHERE namespace = ?",
                    (namespace,)
                )
            else:
                cursor.execute("DELETE FROM cache_items")
            
            conn.commit()
            return cursor.rowcount
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики кеша."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_items,
                    SUM(size) as total_size,
                    SUM(hits) as total_hits,
                    COUNT(CASE WHEN expires_at IS NOT NULL AND expires_at < ? THEN 1 END) as expired_items
                FROM cache_items
            """, (time.time(),))
            
            stats = dict(cursor.fetchone())
            
            return {
                'items': stats['total_items'] or 0,
                'total_size_bytes': stats['total_size'] or 0,
                'total_hits': stats['total_hits'] or 0,
                'expired_items': stats['expired_items'] or 0,
                'backend': 'database',
                'database': self.db_path
            }


class TTLCache:
    """Основной класс кеша с TTL."""
    
    def __init__(
        self,
        backend: CacheBackend = CacheBackend.MEMORY,
        ttl: Optional[int] = 300,  # 5 минут по умолчанию
        max_size: int = 1000,
        **backend_kwargs
    ):
        """
        Инициализация кеша.
        
        Args:
            backend: Тип бэкенда
            ttl: Время жизни элементов по умолчанию (секунды)
            max_size: Максимальный размер кеша (для memory backend)
            **backend_kwargs: Дополнительные параметры для бэкенда
        """
        self.default_ttl = ttl
        self.backend_type = backend
        
        # Инициализация бэкенда
        if backend == CacheBackend.MEMORY:
            self.backend = MemoryCacheBackend(max_size=max_size, **backend_kwargs)
        elif backend == CacheBackend.DATABASE:
            self.backend = DatabaseCacheBackend(**backend_kwargs)
        else:
            raise ValueError(f"Unsupported backend: {backend}")
        
        self.key_builder = CacheKeyBuilder()
    
    def get(self, key: str) -> Any:
        """
        Получение значения из кеша.
        
        Args:
            key: Ключ кеша
            
        Returns:
            Значение или None если не найдено
        """
        item = self.backend.get(key)
        return item.value if item else None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Сохранение значения в кеш.
        
        Args:
            key: Ключ кеша
            value: Значение для кеширования
            ttl: Время жизни в секундах (None для бесконечного)
            
        Returns:
            True если успешно сохранено
        """
        actual_ttl = ttl if ttl is not None else self.default_ttl
        return self.backend.set(key, value, actual_ttl)
    
    def delete(self, key: str) -> bool:
        """
        Удаление значения из кеша.
        
        Args:
            key: Ключ кеша
            
        Returns:
            True если удалено
        """
        return self.backend.delete(key)
    
    def exists(self, key: str) -> bool:
        """
        Проверка существования ключа в кеше.
        
        Args:
            key: Ключ кеша
            
        Returns:
            True если существует и не истек
        """
        return self.backend.exists(key)
    
    def clear(self) -> int:
        """
        Очистка всего кеша.
        
        Returns:
            Количество удаленных элементов
        """
        return self.backend.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики кеша.
        
        Returns:
            Словарь со статистикой
        """
        return self.backend.get_stats()
    
    def cached(
        self, 
        ttl: Optional[int] = None,
        key_prefix: str = "",
        namespace: str = "default"
    ):
        """
        Декоратор для кеширования результатов функций.
        
        Args:
            ttl: Время жизни кеша
            key_prefix: Префикс для ключа
            namespace: Пространство имен
            
        Returns:
            Декорированная функция
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                # Генерируем ключ кеша
                base_key = self.key_builder.build_key(*args, **kwargs)
                full_key = self.key_builder.build_namespaced_key(
                    namespace, 
                    f"{key_prefix}:{base_key}" if key_prefix else base_key
                )
                
                # Пробуем получить из кеша
                cached_value = self.get(full_key)
                if cached_value is not None:
                    return cached_value
                
                # Выполняем функцию
                result = func(*args, **kwargs)
                
                # Сохраняем результат в кеш
                self.set(full_key, result, ttl)
                
                return result
            
            return wrapper
        
        return decorator
    
    def get_multi(self, keys: list[str]) -> Dict[str, Any]:
        """
        Получение нескольких значений за один запрос.
        
        Args:
            keys: Список ключей
            
        Returns:
            Словарь с найденными значениями
        """
        results = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                results[key] = value
        return results
    
    def set_multi(self, items: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """
        Сохранение нескольких значений.
        
        Args:
            items: Словарь ключ-значение
            ttl: Время жизни
            
        Returns:
            True если все успешно сохранено
        """
        success = True
        for key, value in items.items():
            if not self.set(key, value, ttl):
                success = False
        return success
    
    def get_or_set(
        self, 
        key: str, 
        value_callback: callable, 
        ttl: Optional[int] = None
    ) -> Any:
        """
        Получение значения или установка через callback.
        
        Args:
            key: Ключ кеша
            value_callback: Функция для получения значения
            ttl: Время жизни
            
        Returns:
            Значение из кеша или callback
        """
        cached = self.get(key)
        if cached is not None:
            return cached
        
        value = value_callback()
        self.set(key, value, ttl)
        return value


# --- Пример использования ---
def main():
    """Демонстрация работы TTL кеша."""
    
    print("=== Memory Cache Demo ===")
    memory_cache = TTLCache(backend=CacheBackend.MEMORY, ttl=10, max_size=100)
    
    # Базовые операции
    memory_cache.set("user:1", {"name": "Alice", "age": 30}, ttl=5)
    memory_cache.set("config:app", {"theme": "dark", "language": "en"})
    
    print(f"User 1: {memory_cache.get('user:1')}")
    print(f"Config exists: {memory_cache.exists('config:app')}")
    
    # Декоратор кеширования
    @memory_cache.cached(ttl=30, key_prefix="fib")
    def fibonacci(n: int) -> int:
        """Вычисление числа Фибоначчи с кешированием."""
        if n <= 1:
            return n
        return fibonacci(n-1) + fibonacci(n-2)
    
    print(f"Fibonacci(10): {fibonacci(10)}")
    print(f"Cache stats: {memory_cache.get_stats()}")
    
    # Ожидание истечения TTL
    print("\nWaiting for TTL expiration...")
    time.sleep(6)
    print(f"User 1 after TTL: {memory_cache.get('user:1')}")
    
    print("\n=== Database Cache Demo ===")
    db_cache = TTLCache(backend=CacheBackend.DATABASE, ttl=60)
    
    # Работа с базой данных
    db_cache.set("session:abc123", {"user_id": 1, "permissions": ["read", "write"]}, ttl=30)
    db_cache.set("product:42", {"name": "Laptop", "price": 999.99})
    
    print(f"Session: {db_cache.get('session:abc123')}")
    print(f"Product: {db_cache.get('product:42')}")
    print(f"DB Cache stats: {db_cache.get_stats()}")
    
    # Получение нескольких значений
    items = db_cache.get_multi(["session:abc123", "product:42", "nonexistent"])
    print(f"Multi-get: {items}")
    
    # Get or set pattern
    def fetch_expensive_data():
        print("Fetching expensive data...")
        time.sleep(1)
        return {"data": [1, 2, 3, 4, 5]}
    
    result = db_cache.get_or_set("expensive:data", fetch_expensive_data, ttl=10)
    print(f"Expensive data: {result}")
    
    # Второй вызов должен взять из кеша
    result2 = db_cache.get_or_set("expensive:data", fetch_expensive_data, ttl=10)
    print(f"Expensive data (cached): {result2}")
    
    # Очистка
    deleted = memory_cache.clear()
    print(f"\nMemory cache cleared: {deleted} items")
    
    deleted_db = db_cache.clear()
    print(f"Database cache cleared: {deleted_db} items")


if __name__ == "__main__":
    main()