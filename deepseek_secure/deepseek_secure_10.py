import json
import pickle
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import sqlite3
from contextlib import contextmanager
import logging
from queue import Queue as ThreadQueue
import heapq
import asyncio

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MessagePriority(int, Enum):
    """Приоритеты сообщений."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class MessageStatus(str, Enum):
    """Статусы сообщений."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass(order=True)
class PrioritizedMessage:
    """Сообщение с приоритетом для heapq."""
    priority: int
    timestamp: datetime
    message_id: str = field(compare=False)
    message: Any = field(compare=False)
    
    def __init__(self, priority: MessagePriority, message_id: str, message: Any):
        self.priority = -priority.value  # Отрицательное для max-heap
        self.timestamp = datetime.now()
        self.message_id = message_id
        self.message = message


@dataclass
class QueueMessage:
    """Сообщение в очереди."""
    id: str
    queue_name: str
    body: Any
    priority: MessagePriority = MessagePriority.NORMAL
    created_at: datetime = field(default_factory=datetime.now)
    scheduled_for: Optional[datetime] = None
    status: MessageStatus = MessageStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    retry_delay: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    processed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'id': self.id,
            'queue_name': self.queue_name,
            'body': self.body,
            'priority': self.priority.value,
            'created_at': self.created_at.isoformat(),
            'scheduled_for': self.scheduled_for.isoformat() if self.scheduled_for else None,
            'status': self.status.value,
            'attempts': self.attempts,
            'max_attempts': self.max_attempts,
            'retry_delay': self.retry_delay,
            'metadata': self.metadata,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'result': self.result,
            'error': self.error
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueMessage':
        """Десериализация из словаря."""
        return cls(
            id=data['id'],
            queue_name=data['queue_name'],
            body=data['body'],
            priority=MessagePriority(data['priority']),
            created_at=datetime.fromisoformat(data['created_at']),
            scheduled_for=datetime.fromisoformat(data['scheduled_for']) if data['scheduled_for'] else None,
            status=MessageStatus(data['status']),
            attempts=data['attempts'],
            max_attempts=data['max_attempts'],
            retry_delay=data['retry_delay'],
            metadata=data.get('metadata', {}),
            processed_at=datetime.fromisoformat(data['processed_at']) if data['processed_at'] else None,
            result=data.get('result'),
            error=data.get('error')
        )


class MessageSerializer:
    """Сериализатор сообщений."""
    
    @staticmethod
    def serialize(message: QueueMessage) -> bytes:
        """
        Сериализация сообщения.
        
        Args:
            message: Сообщение для сериализации
            
        Returns:
            Сериализованные байты
        """
        data = message.to_dict()
        return pickle.dumps(data)
    
    @staticmethod
    def deserialize(data: bytes) -> QueueMessage:
        """
        Десериализация сообщения.
        
        Args:
            data: Сериализованные данные
            
        Returns:
            Десериализованное сообщение
        """
        data_dict = pickle.loads(data)
        return QueueMessage.from_dict(data_dict)


class QueueStorage:
    """Хранилище очередей."""
    
    def __init__(self, db_path: str = "message_queue.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица сообщений
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    queue_name TEXT NOT NULL,
                    body BLOB NOT NULL,
                    priority INTEGER DEFAULT 1,
                    created_at TIMESTAMP NOT NULL,
                    scheduled_for TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 3,
                    retry_delay REAL DEFAULT 1.0,
                    metadata BLOB,
                    processed_at TIMESTAMP,
                    result BLOB,
                    error TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON messages(queue_name, status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_for ON messages(scheduled_for)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_priority ON messages(priority DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at)")
            
            # Таблица мертвых сообщений (dead letter queue)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dead_letters (
                    id TEXT PRIMARY KEY,
                    original_message_id TEXT NOT NULL,
                    queue_name TEXT NOT NULL,
                    body BLOB NOT NULL,
                    error TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    created_at TIMESTAMP NOT NULL,
                    moved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (original_message_id) REFERENCES messages(id)
                )
            """)
            
            # Таблица статистики очередей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue_stats (
                    queue_name TEXT PRIMARY KEY,
                    total_messages INTEGER DEFAULT 0,
                    pending_messages INTEGER DEFAULT 0,
                    completed_messages INTEGER DEFAULT 0,
                    failed_messages INTEGER DEFAULT 0,
                    dead_letters INTEGER DEFAULT 0,
                    avg_processing_time REAL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    def save_message(self, message: QueueMessage) -> bool:
        """Сохранение сообщения."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO messages 
                    (id, queue_name, body, priority, created_at, scheduled_for, 
                     status, attempts, max_attempts, retry_delay, metadata, 
                     processed_at, result, error, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    message.id,
                    message.queue_name,
                    MessageSerializer.serialize(message),
                    message.priority.value,
                    message.created_at,
                    message.scheduled_for,
                    message.status.value,
                    message.attempts,
                    message.max_attempts,
                    message.retry_delay,
                    pickle.dumps(message.metadata) if message.metadata else None,
                    message.processed_at,
                    pickle.dumps(message.result) if message.result is not None else None,
                    message.error,
                    datetime.now()
                ))
                
                conn.commit()
                
                # Обновляем статистику
                self._update_queue_stats(message.queue_name)
                
                return True
                
        except Exception as e:
            logger.error(f"Error saving message {message.id}: {e}")
            return False
    
    def get_message(self, message_id: str) -> Optional[QueueMessage]:
        """Получение сообщения по ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT body FROM messages WHERE id = ?",
                    (message_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    return MessageSerializer.deserialize(row['body'])
                return None
                
        except Exception as e:
            logger.error(f"Error getting message {message_id}: {e}")
            return None
    
    def get_next_message(self, queue_name: str) -> Optional[QueueMessage]:
        """
        Получение следующего сообщения для обработки.
        
        Args:
            queue_name: Имя очереди
            
        Returns:
            Следующее сообщение или None
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Ищем pending сообщение с наивысшим приоритетом и подходящее по времени
                cursor.execute("""
                    SELECT body FROM messages 
                    WHERE queue_name = ? 
                    AND status = 'pending'
                    AND (scheduled_for IS NULL OR scheduled_for <= ?)
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                """, (queue_name, datetime.now()))
                
                row = cursor.fetchone()
                
                if row:
                    message = MessageSerializer.deserialize(row['body'])
                    
                    # Обновляем статус на processing
                    message.status = MessageStatus.PROCESSING
                    message.attempts += 1
                    self.save_message(message)
                    
                    return message
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting next message for queue {queue_name}: {e}")
            return None
    
    def update_message_status(
        self, 
        message_id: str, 
        status: MessageStatus,
        result: Optional[Any] = None,
        error: Optional[str] = None
    ) -> bool:
        """Обновление статуса сообщения."""
        try:
            message = self.get_message(message_id)
            if not message:
                return False
            
            message.status = status
            message.processed_at = datetime.now()
            
            if result is not None:
                message.result = result
            
            if error is not None:
                message.error = error
            
            return self.save_message(message)
            
        except Exception as e:
            logger.error(f"Error updating message {message_id}: {e}")
            return False
    
    def move_to_dead_letter(self, message: QueueMessage, error: str) -> bool:
        """Перемещение сообщения в dead letter queue."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Сохраняем в dead letters
                cursor.execute("""
                    INSERT INTO dead_letters 
                    (id, original_message_id, queue_name, body, error, attempts, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()),
                    message.id,
                    message.queue_name,
                    MessageSerializer.serialize(message),
                    error,
                    message.attempts,
                    datetime.now()
                ))
                
                # Удаляем из основной очереди
                cursor.execute(
                    "DELETE FROM messages WHERE id = ?",
                    (message.id,)
                )
                
                conn.commit()
                
                # Обновляем статистику
                self._update_queue_stats(message.queue_name)
                
                logger.warning(f"Message {message.id} moved to dead letter queue: {error}")
                return True
                
        except Exception as e:
            logger.error(f"Error moving message to dead letter: {e}")
            return False
    
    def get_queue_stats(self, queue_name: str) -> Dict[str, Any]:
        """Получение статистики очереди."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM queue_stats WHERE queue_name = ?
                """, (queue_name,))
                
                row = cursor.fetchone()
                if row:
                    return dict(row)
                
                # Если статистики нет, создаем запись
                return {
                    'queue_name': queue_name,
                    'total_messages': 0,
                    'pending_messages': 0,
                    'completed_messages': 0,
                    'failed_messages': 0,
                    'dead_letters': 0,
                    'avg_processing_time': 0.0
                }
                
        except Exception as e:
            logger.error(f"Error getting queue stats: {e}")
            return {}
    
    def _update_queue_stats(self, queue_name: str):
        """Обновление статистики очереди."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Считаем статистику
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
                    FROM messages 
                    WHERE queue_name = ?
                """, (queue_name,))
                
                msg_stats = dict(cursor.fetchone())
                
                cursor.execute("""
                    SELECT COUNT(*) as dead_letters 
                    FROM dead_letters 
                    WHERE queue_name = ?
                """, (queue_name,))
                
                dead_stats = dict(cursor.fetchone())
                
                # Среднее время обработки
                cursor.execute("""
                    SELECT AVG(
                        JULIANDAY(processed_at) - JULIANDAY(created_at)
                    ) * 86400.0 as avg_processing_time
                    FROM messages 
                    WHERE queue_name = ? 
                    AND status = 'completed' 
                    AND processed_at IS NOT NULL
                """, (queue_name,))
                
                time_stats = dict(cursor.fetchone())
                
                # Сохраняем статистику
                cursor.execute("""
                    INSERT OR REPLACE INTO queue_stats 
                    (queue_name, total_messages, pending_messages, completed_messages, 
                     failed_messages, dead_letters, avg_processing_time, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    queue_name,
                    msg_stats['total'],
                    msg_stats['pending'],
                    msg_stats['completed'],
                    msg_stats['failed'],
                    dead_stats['dead_letters'],
                    time_stats['avg_processing_time'] or 0.0,
                    datetime.now()
                ))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"Error updating queue stats: {e}")
    
    def cleanup_old_messages(self, retention_days: int = 7) -> int:
        """Очистка старых сообщений."""
        try:
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Удаляем старые completed/failed сообщения
                cursor.execute("""
                    DELETE FROM messages 
                    WHERE status IN ('completed', 'failed') 
                    AND created_at < ?
                """, (cutoff_date,))
                
                deleted = cursor.rowcount
                
                # Удаляем старые dead letters
                cursor.execute(
                    "DELETE FROM dead_letters WHERE created_at < ?",
                    (cutoff_date,)
                )
                
                deleted += cursor.rowcount
                
                conn.commit()
                
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old messages")
                
                return deleted
                
        except Exception as e:
            logger.error(f"Error cleaning up old messages: {e}")
            return 0


class MessageQueue:
    """Очередь сообщений."""
    
    def __init__(
        self,
        name: str,
        storage: QueueStorage,
        max_concurrent: int = 4,
        process_timeout: float = 30.0
    ):
        """
        Инициализация очереди.
        
        Args:
            name: Имя очереди
            storage: Хранилище очереди
            max_concurrent: Максимальное количество параллельных обработчиков
            process_timeout: Таймаут обработки сообщения
        """
        self.name = name
        self.storage = storage
        self.max_concurrent = max_concurrent
        self.process_timeout = process_timeout
        
        self._running = False
        self._workers: List[threading.Thread] = []
        self._worker_semaphore = threading.Semaphore(max_concurrent)
        self._message_callbacks: Dict[str, Callable] = {}
        self._lock = threading.RLock()
        
    def register_handler(self, message_type: str, handler: Callable):
        """
        Регистрация обработчика для типа сообщений.
        
        Args:
            message_type: Тип сообщения (ключ в metadata)
            handler: Функция-обработчик
        """
        with self._lock:
            self._message_callbacks[message_type] = handler
            logger.info(f"Registered handler for message type: {message_type}")
    
    def publish(
        self,
        body: Any,
        message_type: Optional[str] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        delay: Optional[float] = None,
        max_attempts: int = 3,
        retry_delay: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Публикация сообщения в очередь.
        
        Args:
            body: Тело сообщения
            message_type: Тип сообщения
            priority: Приоритет
            delay: Задержка в секундах
            max_attempts: Максимальное количество попыток
            retry_delay: Задержка между попытками
            metadata: Дополнительные метаданные
            
        Returns:
            ID сообщения
        """
        message_id = str(uuid.uuid4())
        
        # Добавляем тип сообщения в метаданные
        message_metadata = metadata or {}
        if message_type:
            message_metadata['type'] = message_type
        
        scheduled_for = None
        if delay:
            scheduled_for = datetime.now() + timedelta(seconds=delay)
        
        message = QueueMessage(
            id=message_id,
            queue_name=self.name,
            body=body,
            priority=priority,
            scheduled_for=scheduled_for,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            metadata=message_metadata
        )
        
        success = self.storage.save_message(message)
        if success:
            logger.debug(f"Published message {message_id} to queue {self.name}")
            return message_id
        else:
            raise RuntimeError(f"Failed to publish message to queue {self.name}")
    
    def _process_message(self, message: QueueMessage):
        """Обработка одного сообщения."""
        try:
            # Получаем обработчик
            message_type = message.metadata.get('type')
            
            if not message_type:
                logger.error(f"Message {message.id} has no type")
                self.storage.update_message_status(
                    message.id, 
                    MessageStatus.FAILED,
                    error="Message type not specified"
                )
                return
            
            handler = self._message_callbacks.get(message_type)
            if not handler:
                logger.error(f"No handler registered for message type: {message_type}")
                self.storage.update_message_status(
                    message.id, 
                    MessageStatus.FAILED,
                    error=f"No handler for type: {message_type}"
                )
                return
            
            # Выполняем обработчик с таймаутом
            start_time = time.time()
            
            try:
                result = handler(message.body, message.metadata)
                
                processing_time = time.time() - start_time
                logger.debug(f"Message {message.id} processed in {processing_time:.2f}s")
                
                self.storage.update_message_status(
                    message.id, 
                    MessageStatus.COMPLETED,
                    result=result
                )
                
            except Exception as e:
                # Обработка ошибок
                error_msg = str(e)
                logger.error(f"Error processing message {message.id}: {error_msg}")
                
                # Проверяем нужно ли повторить
                if message.attempts < message.max_attempts:
                    # Планируем повторную обработку
                    message.status = MessageStatus.PENDING
                    retry_time = datetime.now() + timedelta(seconds=message.retry_delay)
                    message.scheduled_for = retry_time
                    self.storage.save_message(message)
                    
                    logger.info(f"Scheduled retry {message.attempts+1}/{message.max_attempts} for message {message.id}")
                else:
                    # Превышено количество попыток - перемещаем в dead letter
                    self.storage.move_to_dead_letter(message, error_msg)
                    
        finally:
            # Освобождаем семафор
            self._worker_semaphore.release()
    
    def _worker_loop(self, worker_id: int):
        """Цикл работы воркера."""
        logger.info(f"Worker {worker_id} started for queue {self.name}")
        
        while self._running:
            try:
                # Ждем разрешения на обработку
                if not self._worker_semaphore.acquire(timeout=1):
                    continue
                
                # Получаем следующее сообщение
                message = self.storage.get_next_message(self.name)
                
                if message:
                    # Запускаем обработку в отдельном потоке
                    thread = threading.Thread(
                        target=self._process_message,
                        args=(message,),
                        daemon=True,
                        name=f"MessageProcessor-{message.id[:8]}"
                    )
                    thread.start()
                else:
                    # Нет сообщений - освобождаем семафор
                    self._worker_semaphore.release()
                    time.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                time.sleep(1)
    
    def start(self):
        """Запуск очереди."""
        if self._running:
            logger.warning(f"Queue {self.name} is already running")
            return
        
        self._running = True
        
        # Запускаем воркеров
        for i in range(self.max_concurrent):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(i,),
                name=f"QueueWorker-{self.name}-{i}",
                daemon=True
            )
            worker.start()
            self._workers.append(worker)
        
        logger.info(f"Message queue {self.name} started with {self.max_concurrent} workers")
    
    def stop(self):
        """Остановка очереди."""
        self._running = False
        
        # Ждем завершения воркеров
        for worker in self._workers:
            worker.join(timeout=5)
        
        logger.info(f"Message queue {self.name} stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики очереди."""
        stats = self.storage.get_queue_stats(self.name)
        
        with self._lock:
            stats['workers'] = len(self._workers)
            stats['running'] = self._running
            stats['registered_handlers'] = len(self._message_callbacks)
        
        return stats
    
    def get_message_status(self, message_id: str) -> Optional[MessageStatus]:
        """Получение статуса сообщения."""
        message = self.storage.get_message(message_id)
        return message.status if message else None
    
    def retry_failed_messages(self, max_retries: int = 3) -> int:
        """
        Повторная обработка failed сообщений.
        
        Args:
            max_retries: Максимальное количество повторных попыток
            
        Returns:
            Количество сообщений для повторной обработки
        """
        try:
            with self.storage._get_connection() as conn:
                cursor = conn.cursor()
                
                # Находим failed сообщения
                cursor.execute("""
                    SELECT body FROM messages 
                    WHERE queue_name = ? 
                    AND status = 'failed'
                    AND attempts < ?
                """, (self.name, max_retries))
                
                count = 0
                for row in cursor.fetchall():
                    message = MessageSerializer.deserialize(row['body'])
                    
                    # Сбрасываем статус для повторной обработки
                    message.status = MessageStatus.PENDING
                    message.scheduled_for = datetime.now()
                    
                    if self.storage.save_message(message):
                        count += 1
                
                if count > 0:
                    logger.info(f"Scheduled {count} failed messages for retry in queue {self.name}")
                
                return count
                
        except Exception as e:
            logger.error(f"Error retrying failed messages: {e}")
            return 0


class QueueManager:
    """Менеджер очередей."""
    
    def __init__(self, storage: Optional[QueueStorage] = None):
        self.storage = storage or QueueStorage()
        self.queues: Dict[str, MessageQueue] = {}
        self._lock = threading.RLock()
    
    def create_queue(
        self, 
        name: str, 
        max_concurrent: int = 4,
        process_timeout: float = 30.0
    ) -> MessageQueue:
        """
        Создание новой очереди.
        
        Args:
            name: Имя очереди
            max_concurrent: Максимальное количество параллельных обработчиков
            process_timeout: Таймаут обработки сообщения
            
        Returns:
            Созданная очередь
        """
        with self._lock:
            if name in self.queues:
                raise ValueError(f"Queue '{name}' already exists")
            
            queue = MessageQueue(
                name=name,
                storage=self.storage,
                max_concurrent=max_concurrent,
                process_timeout=process_timeout
            )
            
            self.queues[name] = queue
            logger.info(f"Created queue: {name}")
            
            return queue
    
    def get_queue(self, name: str) -> Optional[MessageQueue]:
        """Получение очереди по имени."""
        with self._lock:
            return self.queues.get(name)
    
    def start_all(self):
        """Запуск всех очередей."""
        with self._lock:
            for name, queue in self.queues.items():
                queue.start()
            logger.info(f"Started all queues ({len(self.queues)} total)")
    
    def stop_all(self):
        """Остановка всех очередей."""
        with self._lock:
            for name, queue in self.queues.items():
                queue.stop()
            logger.info(f"Stopped all queues ({len(self.queues)} total)")
    
    def cleanup(self, retention_days: int = 7):
        """Очистка старых сообщений во всех очередях."""
        deleted = self.storage.cleanup_old_messages(retention_days)
        logger.info(f"Cleaned up {deleted} old messages from all queues")
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Получение статистики всех очередей."""
        stats = {}
        with self._lock:
            for name, queue in self.queues.items():
                stats[name] = queue.get_stats()
        return stats


# --- Пример использования ---
def email_handler(body: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    """Обработчик для отправки email."""
    print(f"[EMAIL] Sending email to {body.get('to')}")
    print(f"Subject: {body.get('subject')}")
    print(f"Body: {body.get('body')[:50]}...")
    
    # Имитация отправки
    time.sleep(0.5)
    
    # Имитация случайной ошибки
    import random
    if random.random() < 0.2:  # 20% chance of failure
        raise ConnectionError("Failed to connect to SMTP server")
    
    return f"Email sent successfully to {body.get('to')}"


def notification_handler(body: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    """Обработчик для уведомлений."""
    print(f"[NOTIFICATION] Sending {body.get('type')} notification")
    print(f"User: {body.get('user_id')}")
    print(f"Message: {body.get('message')}")
    
    time.sleep(0.2)
    return f"Notification sent to user {body.get('user_id')}"


def report_handler(body: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    """Обработчик для генерации отчетов."""
    print(f"[REPORT] Generating {body.get('report_type')} report")
    print(f"Period: {body.get('start_date')} to {body.get('end_date')}")
    
    time.sleep(1.5)  # Долгая операция
    return f"Report {body.get('report_type')} generated successfully"


def main():
    """Демонстрация работы системы очередей."""
    print("=== Message Queue System Demo ===")
    
    # Создаем менеджер очередей
    manager = QueueManager()
    
    try:
        # Создаем очереди
        print("\n1. Creating queues...")
        email_queue = manager.create_queue("emails", max_concurrent=2)
        notification_queue = manager.create_queue("notifications", max_concurrent=4)
        report_queue = manager.create_queue("reports", max_concurrent=1)
        
        # Регистрируем обработчики
        print("\n2. Registering handlers...")
        email_queue.register_handler("send_email", email_handler)
        notification_queue.register_handler("send_notification", notification_handler)
        report_queue.register_handler("generate_report", report_handler)
        
        # Запускаем очереди
        print("\n3. Starting queues...")
        manager.start_all()
        
        # Публикуем сообщения
        print("\n4. Publishing messages...")
        
        # Email сообщения
        for i in range(5):
            email_id = email_queue.publish(
                body={
                    "to": f"user{i}@example.com",
                    "subject": f"Test Email {i}",
                    "body": "This is a test email message."
                },
                message_type="send_email",
                priority=MessagePriority.HIGH if i == 0 else MessagePriority.NORMAL,
                max_attempts=2
            )
            print(f"  Published email {i+1}: {email_id}")
        
        # Уведомления
        for i in range(10):
            notif_id = notification_queue.publish(
                body={
                    "user_id": i + 100,
                    "type": "info",
                    "message": f"Notification #{i+1}"
                },
                message_type="send_notification",
                priority=MessagePriority.NORMAL,
                delay=2 if i >= 5 else 0  # Часть уведомлений с задержкой
            )
        
        # Отчеты (с высоким приоритетом)
        report_id = report_queue.publish(
            body={
                "report_type": "monthly_sales",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31"
            },
            message_type="generate_report",
            priority=MessagePriority.CRITICAL
        )
        print(f"  Published report: {report_id}")
        
        # Мониторим статистику
        print("\n5. Monitoring queue statistics...")
        for i in range(15):
            print(f"\n--- Second {i+1} ---")
            
            stats = manager.get_all_stats()
            for queue_name, queue_stats in stats.items():
                pending = queue_stats.get('pending_messages', 0)
                completed = queue_stats.get('completed_messages', 0)
                failed = queue_stats.get('failed_messages', 0)
                
                print(f"  {queue_name}: Pending={pending}, Completed={completed}, Failed={failed}")
            
            if i == 8:
                print("\nRetrying failed messages...")
                for queue in manager.queues.values():
                    retried = queue.retry_failed_messages()
                    if retried > 0:
                        print(f"  Retried {retried} messages in {queue.name}")
            
            time.sleep(1)
        
        # Показываем финальную статистику
        print("\n6. Final statistics:")
        final_stats = manager.get_all_stats()
        for queue_name, queue_stats in final_stats.items():
            print(f"\n{queue_name}:")
            for key, value in queue_stats.items():
                if key not in ['queue_name', 'last_updated']:
                    print(f"  {key}: {value}")
        
        # Очистка
        print("\n7. Cleaning up old messages...")
        manager.cleanup(retention_days=1)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        # Останавливаем очереди
        print("\n8. Stopping all queues...")
        manager.stop_all()
        
        print("\nDemo completed!")


if __name__ == "__main__":
    main()