from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import secrets
import json
import sqlite3
from contextlib import contextmanager
import logging
import threading
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Сессия пользователя."""
    session_id: str
    user_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    
    def is_expired(self) -> bool:
        """Проверка истечения срока сессии."""
        if self.expires_at:
            return datetime.now() > self.expires_at
        return False
    
    def is_valid(self) -> bool:
        """Проверка валидности сессии."""
        return not self.is_expired()
    
    def update_access(self) -> None:
        """Обновление времени последнего доступа."""
        self.last_accessed = datetime.now()


class SessionStorage:
    """Хранилище сессий."""
    
    def __init__(self, db_path: str = "sessions.db", cleanup_interval: int = 3600):
        self.db_path = db_path
        self.cleanup_interval = cleanup_interval
        self._init_database()
        self._running = False
        self._cleanup_thread: Optional[threading.Thread] = None
    
    def _init_database(self):
        """Инициализация БД."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    last_accessed TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP,
                    user_agent TEXT,
                    ip_address TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON sessions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_expires ON sessions(expires_at)")
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def save(self, session: Session) -> bool:
        """Сохранение сессии."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO sessions 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session.session_id,
                    session.user_id,
                    json.dumps(session.data),
                    session.created_at,
                    session.last_accessed,
                    session.expires_at,
                    session.user_agent,
                    session.ip_address
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False
    
    def get(self, session_id: str) -> Optional[Session]:
        """Получение сессии."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (session_id,)
                )
                row = cursor.fetchone()
                if row:
                    return Session(
                        session_id=row['session_id'],
                        user_id=row['user_id'],
                        data=json.loads(row['data']),
                        created_at=datetime.fromisoformat(row['created_at']),
                        last_accessed=datetime.fromisoformat(row['last_accessed']),
                        expires_at=datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None,
                        user_agent=row['user_agent'],
                        ip_address=row['ip_address']
                    )
        except Exception as e:
            logger.error(f"Error getting session: {e}")
        return None
    
    def delete(self, session_id: str) -> bool:
        """Удаление сессии."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM sessions WHERE session_id = ?",
                    (session_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return False
    
    def cleanup_expired(self) -> int:
        """Очистка истекших сессий."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM sessions WHERE expires_at < ?",
                    (datetime.now(),)
                )
                deleted = cursor.rowcount
                conn.commit()
                if deleted:
                    logger.info(f"Cleaned up {deleted} expired sessions")
                return deleted
        except Exception as e:
            logger.error(f"Error cleaning up sessions: {e}")
            return 0
    
    def _cleanup_loop(self):
        """Цикл очистки."""
        while self._running:
            time.sleep(self.cleanup_interval)
            self.cleanup_expired()
    
    def start(self):
        """Запуск фоновой очистки."""
        if self._running:
            return
        self._running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        logger.info("Session cleanup started")
    
    def stop(self):
        """Остановка фоновой очистки."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
        logger.info("Session cleanup stopped")


class SessionManager:
    """Менеджер сессий."""
    
    def __init__(self, storage: Optional[SessionStorage] = None, 
                 default_ttl: int = 3600):
        self.storage = storage or SessionStorage()
        self.default_ttl = default_ttl
        self.storage.start()
    
    def create_session(self, user_id: str, data: Optional[Dict] = None,
                      user_agent: Optional[str] = None,
                      ip_address: Optional[str] = None,
                      ttl: Optional[int] = None) -> Optional[Session]:
        """Создание новой сессии."""
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(seconds=ttl or self.default_ttl)
        
        session = Session(
            session_id=session_id,
            user_id=user_id,
            data=data or {},
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address
        )
        
        if self.storage.save(session):
            logger.info(f"Session created for user {user_id}")
            return session
        return None
    
    def validate_session(self, session_id: str) -> Optional[Session]:
        """Валидация и обновление сессии."""
        session = self.storage.get(session_id)
        if not session or not session.is_valid():
            return None
        
        session.update_access()
        self.storage.save(session)
        return session
    
    def update_session_data(self, session_id: str, 
                           data: Dict[str, Any]) -> bool:
        """Обновление данных сессии."""
        session = self.validate_session(session_id)
        if not session:
            return False
        
        session.data.update(data)
        return self.storage.save(session)
    
    def destroy_session(self, session_id: str) -> bool:
        """Уничтожение сессии."""
        return self.storage.delete(session_id)
    
    def get_user_sessions(self, user_id: str) -> List[Session]:
        """Получение всех сессий пользователя."""
        sessions = []
        try:
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT session_id FROM sessions WHERE user_id = ?",
                    (user_id,)
                )
                for row in cursor.fetchall():
                    session = self.storage.get(row['session_id'])
                    if session:
                        sessions.append(session)
        except Exception as e:
            logger.error(f"Error getting user sessions: {e}")
        return sessions
    
    def destroy_all_user_sessions(self, user_id: str) -> int:
        """Уничтожение всех сессий пользователя."""
        count = 0
        try:
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM sessions WHERE user_id = ?",
                    (user_id,)
                )
                count = cursor.rowcount
                conn.commit()
                logger.info(f"Destroyed {count} sessions for user {user_id}")
        except Exception as e:
            logger.error(f"Error destroying user sessions: {e}")
        return count
    
    def __del__(self):
        self.storage.stop()