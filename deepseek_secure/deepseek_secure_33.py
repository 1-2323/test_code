from typing import Optional, List
from datetime import datetime, timedelta
import secrets
import hashlib
from dataclasses import dataclass
import sqlite3

@dataclass
class APIKey:
    """API ключ."""
    id: str
    user_id: str
    name: str
    key_hash: str
    permissions: List[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True
    
    def is_expired(self) -> bool:
        """Проверка истечения срока действия."""
        if self.expires_at:
            return datetime.now() > self.expires_at
        return False
    
    def is_valid(self) -> bool:
        """Проверка валидности ключа."""
        return self.is_active and not self.is_expired()

class APIKeyManager:
    """Менеджер API ключей."""
    
    def __init__(self, db_path: str = "api_keys.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация БД."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    key_hash TEXT UNIQUE NOT NULL,
                    permissions TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    last_used_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON api_keys(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_key_hash ON api_keys(key_hash)")
            conn.commit()
    
    def generate_key(self, user_id: str, name: str,
                    permissions: List[str],
                    expires_in_days: Optional[int] = None) -> tuple:
        """
        Генерация нового API ключа.
        
        Returns:
            (api_key_object, plain_text_key)
        """
        import uuid
        
        # Генерируем случайный ключ
        plain_key = secrets.token_urlsafe(32)
        
        # Хешируем ключ для хранения
        key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
        
        # Создаем объект ключа
        key_id = str(uuid.uuid4())
        now = datetime.now()
        
        expires_at = None
        if expires_in_days:
            expires_at = now + timedelta(days=expires_in_days)
        
        api_key = APIKey(
            id=key_id,
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            permissions=permissions,
            created_at=now,
            expires_at=expires_at
        )
        
        self._save_key(api_key)
        return api_key, plain_key
    
    def validate_key(self, api_key: str) -> Optional[APIKey]:
        """Валидация API ключа."""
        # Хешируем предоставленный ключ
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        # Ищем в базе
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?",
                (key_hash,)
            )
            row = cursor.fetchone()
            
            if row:
                api_key_obj = self._row_to_key(row)
                
                # Обновляем время последнего использования
                if api_key_obj.is_valid():
                    api_key_obj.last_used_at = datetime.now()
                    self._save_key(api_key_obj)
                    return api_key_obj
        
        return None
    
    def revoke_key(self, key_id: str) -> bool:
        """Отзыв API ключа."""
        key = self.get_key(key_id)
        if not key:
            return False
        
        key.is_active = False
        self._save_key(key)
        return True
    
    def get_key(self, key_id: str) -> Optional[APIKey]:
        """Получение ключа по ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM api_keys WHERE id = ?",
                (key_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return self._row_to_key(row)
        return None
    
    def get_user_keys(self, user_id: str) -> List[APIKey]:
        """Получение ключей пользователя."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            )
            
            keys = []
            for row in cursor.fetchall():
                keys.append(self._row_to_key(row))
            
            return keys
    
    def check_permission(self, api_key: str, permission: str) -> bool:
        """Проверка разрешения для ключа."""
        key_obj = self.validate_key(api_key)
        if not key_obj:
            return False
        
        return permission in key_obj.permissions or 'admin' in key_obj.permissions
    
    def _save_key(self, key: APIKey):
        """Сохранение ключа."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO api_keys VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                key.id,
                key.user_id,
                key.name,
                key.key_hash,
                ','.join(key.permissions),
                key.created_at.isoformat(),
                key.last_used_at.isoformat() if key.last_used_at else None,
                key.expires_at.isoformat() if key.expires_at else None,
                1 if key.is_active else 0
            ))
            conn.commit()
    
    def _row_to_key(self, row) -> APIKey:
        """Преобразование строки БД в APIKey."""
        return APIKey(
            id=row['id'],
            user_id=row['user_id'],
            name=row['name'],
            key_hash=row['key_hash'],
            permissions=row['permissions'].split(','),
            created_at=datetime.fromisoformat(row['created_at']),
            last_used_at=datetime.fromisoformat(row['last_used_at']) if row['last_used_at'] else None,
            expires_at=datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None,
            is_active=bool(row['is_active'])
        )