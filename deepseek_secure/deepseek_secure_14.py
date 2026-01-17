from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import sqlite3
from contextlib import contextmanager
import logging
import json
import threading
import time
from collections import defaultdict, Counter
import hashlib
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Типы событий."""
    # Пользовательские события
    USER_SIGNUP = "user_signup"
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_PROFILE_UPDATE = "user_profile_update"
    
    # Контент
    PAGE_VIEW = "page_view"
    CONTENT_CREATE = "content_create"
    CONTENT_UPDATE = "content_update"
    CONTENT_DELETE = "content_delete"
    CONTENT_SHARE = "content_share"
    
    # Экономика
    PURCHASE = "purchase"
    PAYMENT = "payment"
    REFUND = "refund"
    CART_ADD = "cart_add"
    CART_REMOVE = "cart_remove"
    
    # Системные
    ERROR = "error"
    PERFORMANCE = "performance"
    SECURITY = "security"
    
    # Кастомные
    CUSTOM = "custom"


@dataclass
class Event:
    """Событие аналитики."""
    id: str
    event_type: EventType
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    properties: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'id': self.id,
            'event_type': self.event_type.value,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'timestamp': self.timestamp.isoformat(),
            'properties': self.properties,
            'context': self.context
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """Десериализация из словаря."""
        return cls(
            id=data['id'],
            event_type=EventType(data['event_type']),
            user_id=data.get('user_id'),
            session_id=data.get('session_id'),
            timestamp=datetime.fromisoformat(data['timestamp']),
            properties=data.get('properties', {}),
            context=data.get('context', {})
        )


class EventValidator:
    """Валидатор событий."""
    
    def __init__(self, max_properties: int = 50, max_property_size: int = 1000):
        """
        Инициализация валидатора.
        
        Args:
            max_properties: Максимальное количество свойств
            max_property_size: Максимальный размер значения свойства (в символах)
        """
        self.max_properties = max_properties
        self.max_property_size = max_property_size
    
    def validate(self, event: Event) -> Tuple[bool, List[str]]:
        """
        Валидация события.
        
        Args:
            event: Событие для валидации
            
        Returns:
            (валидно, список ошибок)
        """
        errors = []
        
        # Проверка типа события
        if not event.event_type:
            errors.append("Event type is required")
        
        # Проверка количества свойств
        if len(event.properties) > self.max_properties:
            errors.append(f"Too many properties: {len(event.properties)} > {self.max_properties}")
        
        # Проверка размера значений свойств
        for key, value in event.properties.items():
            if isinstance(value, str) and len(value) > self.max_property_size:
                errors.append(f"Property '{key}' value too long: {len(value)} > {self.max_property_size}")
        
        # Проверка контекста
        if event.context:
            for key, value in event.context.items():
                if isinstance(value, str) and len(value) > self.max_property_size:
                    errors.append(f"Context '{key}' value too long")
        
        return len(errors) == 0, errors


class EventStorage:
    """Хранилище событий."""
    
    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
        self._init_database()
        self._buffer: List[Event] = []
        self._buffer_lock = threading.RLock()
        self._buffer_max_size = 1000
        self._flush_interval = 30  # секунды
        self._running = False
        self._flush_thread: Optional[threading.Thread] = None
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Основная таблица событий
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    session_id TEXT,
                    timestamp TIMESTAMP NOT NULL,
                    properties TEXT,  -- JSON объект
                    context TEXT,  -- JSON объект
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Агрегированные данные
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS event_aggregations (
                    aggregation_type TEXT,
                    period_start TIMESTAMP,
                    event_type TEXT,
                    dimension_key TEXT,
                    dimension_value TEXT,
                    count INTEGER DEFAULT 0,
                    unique_users INTEGER DEFAULT 0,
                    sum_value REAL DEFAULT 0,
                    avg_value REAL DEFAULT 0,
                    PRIMARY KEY (aggregation_type, period_start, event_type, dimension_key, dimension_value)
                )
            """)
            
            # Индексы
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, timestamp)")
            
            # Таблица пользовательских сессий
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    duration INTEGER,
                    event_count INTEGER DEFAULT 0,
                    device_info TEXT,
                    location TEXT,
                    referrer TEXT
                )
            """)
            
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
    
    def save_event(self, event: Event) -> bool:
        """
        Сохранение события (буферизованное).
        
        Args:
            event: Событие для сохранения
            
        Returns:
            True если успешно добавлено в буфер
        """
        with self._buffer_lock:
            self._buffer.append(event)
            
            # Если буфер полон, выполняем сброс
            if len(self._buffer) >= self._buffer_max_size:
                self._flush_buffer()
            
            return True
    
    def _flush_buffer(self):
        """Сброс буфера в БД."""
        with self._buffer_lock:
            if not self._buffer:
                return
            
            events_to_save = self._buffer.copy()
            self._buffer.clear()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                for event in events_to_save:
                    cursor.execute("""
                        INSERT INTO events 
                        (id, event_type, user_id, session_id, timestamp, properties, context)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        event.id,
                        event.event_type.value,
                        event.user_id,
                        event.session_id,
                        event.timestamp,
                        json.dumps(event.properties) if event.properties else None,
                        json.dumps(event.context) if event.context else None
                    ))
                
                conn.commit()
                logger.debug(f"Flushed {len(events_to_save)} events to database")
                
        except Exception as e:
            logger.error(f"Error flushing event buffer: {e}")
            # Возвращаем события в буфер при ошибке
            with self._buffer_lock:
                self._buffer.extend(events_to_save)
    
    def _flush_loop(self):
        """Цикл сброса буфера."""
        logger.info("Event storage flush loop started")
        
        while self._running:
            try:
                time.sleep(self._flush_interval)
                self._flush_buffer()
                
            except Exception as e:
                logger.error(f"Error in flush loop: {e}")
                time.sleep(5)
    
    def start(self):
        """Запуск фоновой обработки."""
        if self._running:
            return
        
        self._running = True
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            name="EventStorageFlush",
            daemon=True
        )
        self._flush_thread.start()
        logger.info("Event storage started")
    
    def stop(self):
        """Остановка фоновой обработки."""
        self._running = False
        
        if self._flush_thread:
            self._flush_thread.join(timeout=10)
        
        # Финальный сброс буфера
        self._flush_buffer()
        logger.info("Event storage stopped")
    
    def get_events(
        self,
        event_type: Optional[EventType] = None,
        user_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[Event]:
        """
        Получение событий с фильтрами.
        
        Args:
            event_type: Тип события
            user_id: ID пользователя
            start_date: Начало периода
            end_date: Конец периода
            limit: Максимальное количество
            offset: Смещение
            
        Returns:
            Список событий
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM events WHERE 1=1"
                params = []
                
                if event_type:
                    query += " AND event_type = ?"
                    params.append(event_type.value)
                
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                
                if start_date:
                    query += " AND timestamp >= ?"
                    params.append(start_date)
                
                if end_date:
                    query += " AND timestamp <= ?"
                    params.append(end_date)
                
                query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                
                cursor.execute(query, params)
                
                events = []
                for row in cursor.fetchall():
                    event = Event(
                        id=row['id'],
                        event_type=EventType(row['event_type']),
                        user_id=row['user_id'],
                        session_id=row['session_id'],
                        timestamp=datetime.fromisoformat(row['timestamp']),
                        properties=json.loads(row['properties']) if row['properties'] else {},
                        context=json.loads(row['context']) if row['context'] else {}
                    )
                    events.append(event)
                
                return events
                
        except Exception as e:
            logger.error(f"Error getting events: {e}")
            return []
    
    def get_event_count(
        self,
        event_type: Optional[EventType] = None,
        user_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """
        Получение количества событий.
        
        Args:
            event_type: Тип события
            user_id: ID пользователя
            start_date: Начало периода
            end_date: Конец периода
            
        Returns:
            Количество событий
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT COUNT(*) as count FROM events WHERE 1=1"
                params = []
                
                if event_type:
                    query += " AND event_type = ?"
                    params.append(event_type.value)
                
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                
                if start_date:
                    query += " AND timestamp >= ?"
                    params.append(start_date)
                
                if end_date:
                    query += " AND timestamp <= ?"
                    params.append(end_date)
                
                cursor.execute(query, params)
                return cursor.fetchone()['count']
                
        except Exception as e:
            logger.error(f"Error getting event count: {e}")
            return 0


class EventAggregator:
    """Агрегатор событий."""
    
    def __init__(self, storage: EventStorage):
        self.storage = storage
    
    def aggregate_hourly(self, date: datetime):
        """
        Агрегация событий по часам.
        
        Args:
            date: Дата для агрегации
        """
        hour_start = date.replace(minute=0, second=0, microsecond=0)
        
        try:
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                
                # Получаем события за час
                cursor.execute("""
                    SELECT 
                        event_type,
                        user_id,
                        COUNT(*) as event_count,
                        COUNT(DISTINCT user_id) as unique_users
                    FROM events 
                    WHERE timestamp >= ? AND timestamp < ?
                    GROUP BY event_type
                """, (hour_start, hour_start + timedelta(hours=1)))
                
                for row in cursor.fetchall():
                    cursor.execute("""
                        INSERT OR REPLACE INTO event_aggregations 
                        (aggregation_type, period_start, event_type, dimension_key, 
                         dimension_value, count, unique_users)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        'hourly',
                        hour_start,
                        row['event_type'],
                        'all',
                        'all',
                        row['event_count'],
                        row['unique_users']
                    ))
                
                conn.commit()
                logger.debug(f"Aggregated hourly data for {hour_start}")
                
        except Exception as e:
            logger.error(f"Error aggregating hourly data: {e}")
    
    def aggregate_daily(self, date: datetime):
        """
        Агрегация событий по дням.
        
        Args:
            date: Дата для агрегации
        """
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        try:
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                
                # Основные метрики по типам событий
                cursor.execute("""
                    SELECT 
                        event_type,
                        COUNT(*) as event_count,
                        COUNT(DISTINCT user_id) as unique_users
                    FROM events 
                    WHERE timestamp >= ? AND timestamp < ?
                    GROUP BY event_type
                """, (day_start, day_start + timedelta(days=1)))
                
                for row in cursor.fetchall():
                    cursor.execute("""
                        INSERT OR REPLACE INTO event_aggregations 
                        (aggregation_type, period_start, event_type, dimension_key, 
                         dimension_value, count, unique_users)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        'daily',
                        day_start,
                        row['event_type'],
                        'all',
                        'all',
                        row['event_count'],
                        row['unique_users']
                    ))
                
                # Агрегация по пользователям
                cursor.execute("""
                    SELECT 
                        user_id,
                        COUNT(*) as event_count
                    FROM events 
                    WHERE timestamp >= ? AND timestamp < ?
                    AND user_id IS NOT NULL
                    GROUP BY user_id
                    ORDER BY event_count DESC
                    LIMIT 100
                """, (day_start, day_start + timedelta(days=1)))
                
                for row in cursor.fetchall():
                    cursor.execute("""
                        INSERT OR REPLACE INTO event_aggregations 
                        (aggregation_type, period_start, event_type, dimension_key, 
                         dimension_value, count)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        'daily_user_stats',
                        day_start,
                        'all',
                        'user_id',
                        row['user_id'],
                        row['event_count']
                    ))
                
                conn.commit()
                logger.debug(f"Aggregated daily data for {day_start}")
                
        except Exception as e:
            logger.error(f"Error aggregating daily data: {e}")


class AnalyticsService:
    """Сервис аналитики."""
    
    def __init__(self, storage: Optional[EventStorage] = None):
        self.storage = storage or EventStorage()
        self.validator = EventValidator()
        self.aggregator = EventAggregator(self.storage)
        self._session_cache: Dict[str, Dict[str, Any]] = {}
    
    def track_event(
        self,
        event_type: EventType,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Трекинг события.
        
        Args:
            event_type: Тип события
            user_id: ID пользователя
            session_id: ID сессии
            properties: Свойства события
            context: Контекст
            
        Returns:
            ID события или None при ошибке
        """
        # Генерация ID события
        event_id = hashlib.md5(
            f"{event_type.value}_{user_id}_{session_id}_{time.time_ns()}".encode()
        ).hexdigest()
        
        event = Event(
            id=event_id,
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            properties=properties or {},
            context=context or {}
        )
        
        # Валидация
        is_valid, errors = self.validator.validate(event)
        if not is_valid:
            logger.error(f"Event validation failed: {errors}")
            return None
        
        # Сохранение
        success = self.storage.save_event(event)
        if success:
            logger.debug(f"Event tracked: {event_type.value} ({event_id})")
            return event_id
        
        return None
    
    def track_page_view(
        self,
        page_path: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        referrer: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Трекинг просмотра страницы.
        
        Args:
            page_path: Путь страницы
            user_id: ID пользователя
            session_id: ID сессии
            referrer: Реферер
            properties: Дополнительные свойства
            
        Returns:
            ID события
        """
        props = properties or {}
        props['page_path'] = page_path
        props['page_title'] = props.get('page_title', page_path)
        
        context = {
            'user_agent': props.get('user_agent'),
            'ip_address': props.get('ip_address'),
            'screen_resolution': props.get('screen_resolution'),
            'referrer': referrer
        }
        
        return self.track_event(
            event_type=EventType.PAGE_VIEW,
            user_id=user_id,
            session_id=session_id,
            properties=props,
            context=context
        )
    
    def get_event_metrics(
        self,
        event_type: EventType,
        start_date: datetime,
        end_date: datetime,
        group_by: str = 'day'  # 'hour', 'day', 'week', 'month'
    ) -> Dict[str, Any]:
        """
        Получение метрик по событиям.
        
        Args:
            event_type: Тип события
            start_date: Начало периода
            end_date: Конец периода
            group_by: Группировка
            
        Returns:
            Метрики
        """
        try:
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                
                if group_by == 'hour':
                    time_format = "strftime('%Y-%m-%d %H:00:00', timestamp)"
                elif group_by == 'day':
                    time_format = "date(timestamp)"
                elif group_by == 'week':
                    time_format = "strftime('%Y-W%W', timestamp)"
                elif group_by == 'month':
                    time_format = "strftime('%Y-%m', timestamp)"
                else:
                    time_format = "date(timestamp)"
                
                cursor.execute(f"""
                    SELECT 
                        {time_format} as period,
                        COUNT(*) as event_count,
                        COUNT(DISTINCT user_id) as unique_users,
                        COUNT(DISTINCT session_id) as unique_sessions
                    FROM events 
                    WHERE event_type = ? 
                    AND timestamp >= ? AND timestamp <= ?
                    GROUP BY period
                    ORDER BY period
                """, (event_type.value, start_date, end_date))
                
                metrics = {
                    'total_events': 0,
                    'total_users': 0,
                    'total_sessions': 0,
                    'periods': []
                }
                
                seen_users = set()
                seen_sessions = set()
                
                for row in cursor.fetchall():
                    period_data = {
                        'period': row['period'],
                        'event_count': row['event_count'],
                        'unique_users': row['unique_users'],
                        'unique_sessions': row['unique_sessions']
                    }
                    
                    metrics['periods'].append(period_data)
                    metrics['total_events'] += row['event_count']
                    
                    # Для получения уникальных пользователей и сессий за весь период
                    # нужен отдельный запрос
                
                # Получаем уникальных пользователей за весь период
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as total_users
                    FROM events 
                    WHERE event_type = ? 
                    AND timestamp >= ? AND timestamp <= ?
                    AND user_id IS NOT NULL
                """, (event_type.value, start_date, end_date))
                
                total_users_row = cursor.fetchone()
                metrics['total_users'] = total_users_row['total_users'] if total_users_row else 0
                
                # Получаем уникальные сессии
                cursor.execute("""
                    SELECT COUNT(DISTINCT session_id) as total_sessions
                    FROM events 
                    WHERE event_type = ? 
                    AND timestamp >= ? AND timestamp <= ?
                    AND session_id IS NOT NULL
                """, (event_type.value, start_date, end_date))
                
                total_sessions_row = cursor.fetchone()
                metrics['total_sessions'] = total_sessions_row['total_sessions'] if total_sessions_row else 0
                
                return metrics
                
        except Exception as e:
            logger.error(f"Error getting event metrics: {e}")
            return {}
    
    def get_funnel_analysis(
        self,
        steps: List[EventType],
        start_date: datetime,
        end_date: datetime,
        user_id_field: str = 'user_id'
    ) -> Dict[str, Any]:
        """
        Анализ воронки событий.
        
        Args:
            steps: Шаги воронки
            start_date: Начало периода
            end_date: Конец периода
            user_id_field: Поле для идентификации пользователя
            
        Returns:
            Данные воронки
        """
        if len(steps) < 2:
            return {'error': 'At least 2 steps required'}
        
        try:
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                
                funnel_data = {
                    'steps': [],
                    'total_conversion': 0.0,
                    'drop_offs': []
                }
                
                # Получаем пользователей для первого шага
                step_query = f"""
                    SELECT DISTINCT {user_id_field}
                    FROM events 
                    WHERE event_type = ? 
                    AND timestamp >= ? AND timestamp <= ?
                    AND {user_id_field} IS NOT NULL
                """
                
                prev_users = set()
                total_start_users = 0
                
                for i, step in enumerate(steps):
                    cursor.execute(
                        step_query,
                        (step.value, start_date, end_date)
                    )
                    
                    current_users = {row[user_id_field] for row in cursor.fetchall()}
                    
                    if i == 0:
                        total_start_users = len(current_users)
                        step_users = current_users
                    else:
                        # Пользователи, которые прошли все предыдущие шаги
                        step_users = current_users.intersection(prev_users)
                    
                    step_data = {
                        'step': step.value,
                        'user_count': len(step_users),
                        'conversion_from_previous': 0.0,
                        'conversion_from_start': 0.0
                    }
                    
                    if i == 0:
                        step_data['conversion_from_start'] = 100.0
                    else:
                        if len(prev_users) > 0:
                            step_data['conversion_from_previous'] = (len(step_users) / len(prev_users)) * 100
                        if total_start_users > 0:
                            step_data['conversion_from_start'] = (len(step_users) / total_start_users) * 100
                    
                    funnel_data['steps'].append(step_data)
                    
                    if i > 0 and len(prev_users) > 0:
                        drop_off = len(prev_users) - len(step_users)
                        funnel_data['drop_offs'].append({
                            'from_step': steps[i-1].value,
                            'to_step': step.value,
                            'drop_off_count': drop_off,
                            'drop_off_percentage': (drop_off / len(prev_users)) * 100
                        })
                    
                    prev_users = step_users
                
                if total_start_users > 0 and len(prev_users) > 0:
                    funnel_data['total_conversion'] = (len(prev_users) / total_start_users) * 100
                
                return funnel_data
                
        except Exception as e:
            logger.error(f"Error calculating funnel: {e}")
            return {}
    
    def get_user_behavior(
        self,
        user_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Получение поведения пользователя.
        
        Args:
            user_id: ID пользователя
            start_date: Начало периода
            end_date: Конец периода
            limit: Максимальное количество событий
            
        Returns:
            Данные о поведении
        """
        events = self.storage.get_events(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        if not events:
            return {}
        
        behavior = {
            'user_id': user_id,
            'total_events': len(events),
            'first_event': events[-1].timestamp if events else None,
            'last_event': events[0].timestamp if events else None,
            'event_types': Counter(),
            'sessions': {},
            'frequency': {}
        }
        
        for event in events:
            behavior['event_types'][event.event_type.value] += 1
            
            # Группировка по сессиям
            if event.session_id:
                if event.session_id not in behavior['sessions']:
                    behavior['sessions'][event.session_id] = {
                        'event_count': 0,
                        'event_types': Counter(),
                        'first_event': event.timestamp,
                        'last_event': event.timestamp
                    }
                
                session_data = behavior['sessions'][event.session_id]
                session_data['event_count'] += 1
                session_data['event_types'][event.event_type.value] += 1
                
                if event.timestamp < session_data['first_event']:
                    session_data['first_event'] = event.timestamp
                if event.timestamp > session_data['last_event']:
                    session_data['last_event'] = event.timestamp
        
        return behavior
    
    def start_service(self):
        """Запуск сервиса."""
        self.storage.start()
        logger.info("Analytics service started")
    
    def stop_service(self):
        """Остановка сервиса."""
        self.storage.stop()
        logger.info("Analytics service stopped")