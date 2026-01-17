import asyncio
import threading
import time
from typing import Any, Callable, Optional, Dict, List, Union
from datetime import datetime, timedelta
from enum import Enum
import pickle
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
import logging
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import inspect

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Статусы задач."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    """Приоритеты задач."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Task:
    """Класс задачи для планировщика."""
    id: str
    func: Callable
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    schedule_time: Optional[datetime] = None
    interval: Optional[timedelta] = None
    max_retries: int = 0
    retry_delay: float = 1.0
    priority: TaskPriority = TaskPriority.NORMAL
    timeout: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Валидация после инициализации."""
        if self.interval and self.interval.total_seconds() <= 0:
            raise ValueError("Interval must be positive")
        if self.max_retries < 0:
            raise ValueError("Max retries cannot be negative")
        if self.retry_delay < 0:
            raise ValueError("Retry delay cannot be negative")
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'id': self.id,
            'func_name': self.func.__name__ if hasattr(self.func, '__name__') else str(self.func),
            'module': self.func.__module__ if hasattr(self.func, '__module__') else None,
            'args': self.args,
            'kwargs': self.kwargs,
            'schedule_time': self.schedule_time.isoformat() if self.schedule_time else None,
            'interval': self.interval.total_seconds() if self.interval else None,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'priority': self.priority.value,
            'timeout': self.timeout,
            'created_at': self.created_at.isoformat(),
            'status': self.status.value,
            'result': self.result,
            'error': self.error,
            'attempts': self.attempts,
            'tags': self.tags
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Десериализация из словаря."""
        # Внимание: функция не может быть восстановлена из словаря
        # В реальном приложении нужна регистрация функций
        return cls(
            id=data['id'],
            func=None,  # Будет восстановлено позже
            args=tuple(data['args']),
            kwargs=data['kwargs'],
            schedule_time=datetime.fromisoformat(data['schedule_time']) if data['schedule_time'] else None,
            interval=timedelta(seconds=data['interval']) if data['interval'] else None,
            max_retries=data['max_retries'],
            retry_delay=data['retry_delay'],
            priority=TaskPriority(data['priority']),
            timeout=data['timeout'],
            created_at=datetime.fromisoformat(data['created_at']),
            status=TaskStatus(data['status']),
            result=data['result'],
            error=data['error'],
            attempts=data['attempts'],
            tags=data['tags']
        )


class TaskStorage:
    """Хранилище задач."""
    
    def __init__(self, db_path: str = "tasks.db"):
        self.db_path = db_path
        self._init_database()
        self._function_registry: Dict[str, Callable] = {}
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    func_name TEXT NOT NULL,
                    module TEXT,
                    args BLOB,
                    kwargs BLOB,
                    schedule_time TIMESTAMP,
                    interval_seconds REAL,
                    max_retries INTEGER DEFAULT 0,
                    retry_delay REAL DEFAULT 1.0,
                    priority INTEGER DEFAULT 1,
                    timeout REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    result BLOB,
                    error TEXT,
                    attempts INTEGER DEFAULT 0,
                    tags TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_schedule_time ON tasks(schedule_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_priority ON tasks(priority)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags ON tasks(tags)")
            
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
    
    def _serialize(self, obj: Any) -> bytes:
        """Сериализация объекта."""
        return pickle.dumps(obj)
    
    def _deserialize(self, data: bytes) -> Any:
        """Десериализация объекта."""
        if data is None:
            return None
        return pickle.loads(data)
    
    def register_function(self, func: Callable, name: Optional[str] = None):
        """
        Регистрация функции для последующего восстановления.
        
        Args:
            func: Функция для регистрации
            name: Имя функции (по умолчанию берется из func.__name__)
        """
        func_name = name or func.__name__
        self._function_registry[func_name] = func
        logger.debug(f"Registered function: {func_name}")
    
    def save_task(self, task: Task) -> bool:
        """Сохранение задачи в хранилище."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO tasks 
                    (id, func_name, module, args, kwargs, schedule_time, interval_seconds,
                     max_retries, retry_delay, priority, timeout, created_at, status,
                     result, error, attempts, tags, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task.id,
                    task.func.__name__ if hasattr(task.func, '__name__') else str(task.func),
                    task.func.__module__ if hasattr(task.func, '__module__') else None,
                    self._serialize(task.args),
                    self._serialize(task.kwargs),
                    task.schedule_time,
                    task.interval.total_seconds() if task.interval else None,
                    task.max_retries,
                    task.retry_delay,
                    task.priority.value,
                    task.timeout,
                    task.created_at,
                    task.status.value,
                    self._serialize(task.result) if task.result is not None else None,
                    task.error,
                    task.attempts,
                    ','.join(task.tags) if task.tags else None,
                    datetime.now()
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving task {task.id}: {e}")
            return False
    
    def load_task(self, task_id: str) -> Optional[Task]:
        """Загрузка задачи из хранилища."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM tasks WHERE id = ?",
                    (task_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                # Восстанавливаем функцию из реестра
                func_name = row['func_name']
                func = self._function_registry.get(func_name)
                
                if not func:
                    logger.warning(f"Function {func_name} not found in registry")
                    # Можно использовать заглушку
                    func = lambda *args, **kwargs: None
                
                # Создаем задачу
                task = Task(
                    id=row['id'],
                    func=func,
                    args=self._deserialize(row['args']),
                    kwargs=self._deserialize(row['kwargs']),
                    schedule_time=datetime.fromisoformat(row['schedule_time']) if row['schedule_time'] else None,
                    interval=timedelta(seconds=row['interval_seconds']) if row['interval_seconds'] else None,
                    max_retries=row['max_retries'],
                    retry_delay=row['retry_delay'],
                    priority=TaskPriority(row['priority']),
                    timeout=row['timeout'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    status=TaskStatus(row['status']),
                    result=self._deserialize(row['result']) if row['result'] is not None else None,
                    error=row['error'],
                    attempts=row['attempts'],
                    tags=row['tags'].split(',') if row['tags'] else []
                )
                
                return task
                
        except Exception as e:
            logger.error(f"Error loading task {task_id}: {e}")
            return None
    
    def get_pending_tasks(self, limit: int = 100) -> List[Task]:
        """Получение pending задач."""
        tasks = []
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM tasks 
                    WHERE status = 'pending' 
                    AND (schedule_time IS NULL OR schedule_time <= ?)
                    ORDER BY priority DESC, created_at ASC
                    LIMIT ?
                """, (datetime.now(), limit))
                
                for row in cursor.fetchall():
                    task = self.load_task(row['id'])
                    if task:
                        tasks.append(task)
                        
        except Exception as e:
            logger.error(f"Error getting pending tasks: {e}")
        
        return tasks
    
    def update_task_status(self, task_id: str, status: TaskStatus, 
                          result: Any = None, error: Optional[str] = None) -> bool:
        """Обновление статуса задачи."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                updates = {
                    'status': status.value,
                    'last_updated': datetime.now()
                }
                
                if result is not None:
                    updates['result'] = self._serialize(result)
                
                if error is not None:
                    updates['error'] = error
                
                # Увеличиваем счетчик попыток для running задач
                if status == TaskStatus.RUNNING:
                    cursor.execute(
                        "UPDATE tasks SET attempts = attempts + 1 WHERE id = ?",
                        (task_id,)
                    )
                
                # Собираем SQL запрос
                set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
                values = list(updates.values()) + [task_id]
                
                cursor.execute(
                    f"UPDATE tasks SET {set_clause} WHERE id = ?",
                    values
                )
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error updating task {task_id}: {e}")
            return False
    
    def delete_task(self, task_id: str) -> bool:
        """Удаление задачи."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM tasks WHERE id = ?",
                    (task_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error deleting task {task_id}: {e}")
            return False
    
    def get_task_stats(self) -> Dict[str, Any]:
        """Получение статистики по задачам."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                        COUNT(CASE WHEN status = 'running' THEN 1 END) as running,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                        SUM(attempts) as total_attempts,
                        AVG(attempts) as avg_attempts
                    FROM tasks
                """)
                
                row = cursor.fetchone()
                return dict(row)
                
        except Exception as e:
            logger.error(f"Error getting task stats: {e}")
            return {}


class TaskExecutor:
    """Исполнитель задач."""
    
    def __init__(self, max_workers: int = 4, use_processes: bool = False):
        """
        Инициализация исполнителя.
        
        Args:
            max_workers: Максимальное количество рабочих потоков/процессов
            use_processes: Использовать процессы вместо потоков
        """
        self.max_workers = max_workers
        self.use_processes = use_processes
        
        if use_processes:
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
            logger.info(f"Initialized process pool executor with {max_workers} workers")
        else:
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
            logger.info(f"Initialized thread pool executor with {max_workers} workers")
        
        self.running_tasks: Dict[str, asyncio.Future] = {}
    
    def execute_task(self, task: Task) -> Any:
        """
        Выполнение задачи.
        
        Args:
            task: Задача для выполнения
            
        Returns:
            Результат выполнения
            
        Raises:
            Exception: Если задача завершилась с ошибкой
        """
        try:
            # Проверяем является ли функция асинхронной
            if inspect.iscoroutinefunction(task.func):
                # Для асинхронных функций нужен event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        task.func(*task.args, **task.kwargs)
                    )
                finally:
                    loop.close()
            else:
                # Синхронная функция
                result = task.func(*task.args, **task.kwargs)
            
            return result
            
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            raise
    
    async def execute_task_async(self, task: Task) -> Any:
        """
        Асинхронное выполнение задачи.
        
        Args:
            task: Задача для выполнения
            
        Returns:
            Результат выполнения
        """
        try:
            # Запускаем в отдельном потоке/процессе
            loop = asyncio.get_event_loop()
            
            # Для асинхронных функций выполняем напрямую
            if inspect.iscoroutinefunction(task.func):
                result = await task.func(*task.args, **task.kwargs)
            else:
                # Синхронные функции запускаем в executor
                result = await loop.run_in_executor(
                    self.executor,
                    self.execute_task,
                    task
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Task {task.id} failed in async mode: {e}")
            raise
    
    def shutdown(self):
        """Завершение работы исполнителя."""
        self.executor.shutdown(wait=True)
        logger.info("Task executor shutdown complete")


class TaskScheduler:
    """Планировщик задач."""
    
    def __init__(
        self,
        storage: Optional[TaskStorage] = None,
        executor: Optional[TaskExecutor] = None,
        check_interval: float = 1.0
    ):
        """
        Инициализация планировщика.
        
        Args:
            storage: Хранилище задач (опционально)
            executor: Исполнитель задач (опционально)
            check_interval: Интервал проверки задач в секундах
        """
        self.storage = storage or TaskStorage()
        self.executor = executor or TaskExecutor(max_workers=4)
        self.check_interval = check_interval
        
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.RLock()
        
        # Регистрируем системные функции
        self._register_system_functions()
    
    def _register_system_functions(self):
        """Регистрация системных функций."""
        # Функция для отложенного выполнения
        def delayed_print(*args, **kwargs):
            print(*args, **kwargs)
        
        self.storage.register_function(delayed_print, "delayed_print")
        
        # Функция для отправки email (заглушка)
        def send_email(to: str, subject: str, body: str):
            print(f"[EMAIL] To: {to}, Subject: {subject}")
            print(f"Body: {body}")
        
        self.storage.register_function(send_email, "send_email")
    
    def schedule(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        delay: Optional[float] = None,
        schedule_time: Optional[datetime] = None,
        interval: Optional[float] = None,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: Optional[float] = None,
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Планирование задачи.
        
        Args:
            func: Функция для выполнения
            args: Аргументы функции
            kwargs: Именованные аргументы
            delay: Задержка в секундах
            schedule_time: Время запуска
            interval: Интервал повторения в секундах
            max_retries: Максимальное количество повторений при ошибке
            retry_delay: Задержка между повторениями
            priority: Приоритет задачи
            timeout: Таймаут выполнения
            tags: Теги для группировки задач
            
        Returns:
            ID задачи
        """
        # Регистрируем функцию в хранилище
        func_name = func.__name__
        self.storage.register_function(func, func_name)
        
        # Определяем время запуска
        if delay is not None:
            schedule_time = datetime.now() + timedelta(seconds=delay)
        
        # Определяем интервал
        interval_td = timedelta(seconds=interval) if interval else None
        
        # Создаем задачу
        task_id = str(uuid4())
        task = Task(
            id=task_id,
            func=func,
            args=args,
            kwargs=kwargs or {},
            schedule_time=schedule_time,
            interval=interval_td,
            max_retries=max_retries,
            retry_delay=retry_delay,
            priority=priority,
            timeout=timeout,
            tags=tags or []
        )
        
        # Сохраняем в хранилище
        self.storage.save_task(task)
        
        # Добавляем в локальный кеш
        with self._lock:
            self._tasks[task_id] = task
        
        logger.info(f"Scheduled task {task_id} ({func_name})")
        return task_id
    
    def schedule_at(
        self,
        func: Callable,
        schedule_time: datetime,
        **kwargs
    ) -> str:
        """
        Планирование задачи на конкретное время.
        
        Args:
            func: Функция для выполнения
            schedule_time: Время запуска
            **kwargs: Дополнительные параметры
            
        Returns:
            ID задачи
        """
        return self.schedule(func, schedule_time=schedule_time, **kwargs)
    
    def schedule_delayed(
        self,
        func: Callable,
        delay: float,
        **kwargs
    ) -> str:
        """
        Планирование задачи с задержкой.
        
        Args:
            func: Функция для выполнения
            delay: Задержка в секундах
            **kwargs: Дополнительные параметры
            
        Returns:
            ID задачи
        """
        return self.schedule(func, delay=delay, **kwargs)
    
    def schedule_recurring(
        self,
        func: Callable,
        interval: float,
        **kwargs
    ) -> str:
        """
        Планирование периодической задачи.
        
        Args:
            func: Функция для выполнения
            interval: Интервал в секундах
            **kwargs: Дополнительные параметры
            
        Returns:
            ID задачи
        """
        return self.schedule(func, interval=interval, **kwargs)
    
    async def _process_task(self, task: Task):
        """Обработка одной задачи."""
        try:
            # Обновляем статус на running
            task.status = TaskStatus.RUNNING
            self.storage.update_task_status(task.id, task.status)
            
            # Выполняем задачу с таймаутом
            if task.timeout:
                try:
                    result = await asyncio.wait_for(
                        self.executor.execute_task_async(task),
                        timeout=task.timeout
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(f"Task {task.id} timed out after {task.timeout} seconds")
            else:
                result = await self.executor.execute_task_async(task)
            
            # Успешное завершение
            task.status = TaskStatus.COMPLETED
            task.result = result
            self.storage.update_task_status(task.id, task.status, result=result)
            
            logger.info(f"Task {task.id} completed successfully")
            
            # Если задача периодическая, планируем следующее выполнение
            if task.interval:
                next_time = datetime.now() + task.interval
                new_task = Task(
                    id=str(uuid4()),
                    func=task.func,
                    args=task.args,
                    kwargs=task.kwargs,
                    schedule_time=next_time,
                    interval=task.interval,
                    max_retries=task.max_retries,
                    retry_delay=task.retry_delay,
                    priority=task.priority,
                    timeout=task.timeout,
                    tags=task.tags
                )
                
                self.storage.save_task(new_task)
                with self._lock:
                    self._tasks[new_task.id] = new_task
                
                logger.info(f"Scheduled next execution for recurring task {task.id} at {next_time}")
            
        except Exception as e:
            # Обработка ошибок
            task.attempts += 1
            task.error = str(e)
            
            if task.attempts <= task.max_retries:
                # Планируем повторное выполнение
                task.status = TaskStatus.PENDING
                retry_time = datetime.now() + timedelta(seconds=task.retry_delay)
                task.schedule_time = retry_time
                
                self.storage.update_task_status(
                    task.id, task.status, error=f"Will retry: {task.error}"
                )
                
                logger.warning(f"Task {task.id} failed, scheduled retry {task.attempts}/{task.max_retries} at {retry_time}")
                
            else:
                # Превышено количество попыток
                task.status = TaskStatus.FAILED
                self.storage.update_task_status(task.id, task.status, error=task.error)
                
                logger.error(f"Task {task.id} failed after {task.attempts} attempts: {task.error}")
        
        finally:
            # Удаляем из running задач
            with self._lock:
                if task.id in self._tasks:
                    # Если задача завершена или провалена, удаляем из памяти
                    if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                        del self._tasks[task.id]
    
    def _scheduler_loop(self):
        """Основной цикл планировщика."""
        logger.info("Scheduler loop started")
        
        while self._running:
            try:
                # Получаем pending задачи
                pending_tasks = self.storage.get_pending_tasks(limit=10)
                
                for task in pending_tasks:
                    # Проверяем время запуска
                    if task.schedule_time and task.schedule_time > datetime.now():
                        continue
                    
                    # Обновляем в локальном кеше
                    with self._lock:
                        self._tasks[task.id] = task
                    
                    # Запускаем асинхронную обработку
                    asyncio.run(self._process_task(task))
                
                # Небольшая пауза
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(5)  # Пауза при ошибке
    
    def start(self):
        """Запуск планировщика."""
        if self._running:
            logger.warning("Scheduler is already running")
            return
        
        self._running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="TaskScheduler",
            daemon=True
        )
        self._scheduler_thread.start()
        
        logger.info("Task scheduler started")
    
    def stop(self):
        """Остановка планировщика."""
        self._running = False
        
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=10)
        
        self.executor.shutdown()
        logger.info("Task scheduler stopped")
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Отмена задачи.
        
        Args:
            task_id: ID задачи
            
        Returns:
            True если задача отменена
        """
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                task.status = TaskStatus.CANCELLED
                
                self.storage.update_task_status(task_id, TaskStatus.CANCELLED)
                del self._tasks[task_id]
                
                logger.info(f"Task {task_id} cancelled")
                return True
        
        # Если задача не в памяти, проверяем хранилище
        task = self.storage.load_task(task_id)
        if task and task.status == TaskStatus.PENDING:
            return self.storage.update_task_status(task_id, TaskStatus.CANCELLED)
        
        return False
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """
        Получение статуса задачи.
        
        Args:
            task_id: ID задачи
            
        Returns:
            Статус задачи или None если не найдена
        """
        with self._lock:
            if task_id in self._tasks:
                return self._tasks[task_id].status
        
        task = self.storage.load_task(task_id)
        return task.status if task else None
    
    def get_task_result(self, task_id: str) -> Any:
        """
        Получение результата задачи.
        
        Args:
            task_id: ID задачи
            
        Returns:
            Результат задачи или None
        """
        task = self.storage.load_task(task_id)
        return task.result if task else None
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики планировщика.
        
        Returns:
            Словарь со статистикой
        """
        storage_stats = self.storage.get_task_stats()
        
        with self._lock:
            memory_stats = {
                'tasks_in_memory': len(self._tasks),
                'running': self._running
            }
        
        return {**storage_stats, **memory_stats}


# --- Пример использования ---
def example_task(name: str, value: int) -> str:
    """Пример задачи для выполнения."""
    print(f"Task {name} started with value {value}")
    time.sleep(2)  # Имитация долгой работы
    result = f"Processed {name}: {value * 2}"
    print(f"Task {name} completed: {result}")
    return result


async def example_async_task(name: str) -> str:
    """Пример асинхронной задачи."""
    print(f"Async task {name} started")
    await asyncio.sleep(1)
    result = f"Async {name} done"
    print(f"Async task {name} completed")
    return result


def failing_task():
    """Задача, которая всегда падает."""
    raise ValueError("This task always fails!")


def main():
    """Демонстрация работы планировщика."""
    print("=== Task Scheduler Demo ===")
    
    # Создаем планировщик
    scheduler = TaskScheduler(check_interval=0.5)
    
    try:
        # Запускаем планировщик
        scheduler.start()
        
        # Планируем различные задачи
        print("\n1. Scheduling immediate task...")
        task1_id = scheduler.schedule(example_task, args=("immediate", 5))
        
        print("\n2. Scheduling delayed task (3 seconds)...")
        task2_id = scheduler.schedule_delayed(example_task, delay=3, args=("delayed", 10))
        
        print("\n3. Scheduling recurring task (every 5 seconds)...")
        task3_id = scheduler.schedule_recurring(
            example_task,
            interval=5,
            args=("recurring", 15),
            max_retries=2
        )
        
        print("\n4. Scheduling task for specific time...")
        future_time = datetime.now() + timedelta(seconds=2)
        task4_id = scheduler.schedule_at(example_task, future_time, args=("scheduled", 20))
        
        print("\n5. Scheduling failing task with retries...")
        task5_id = scheduler.schedule(
            failing_task,
            max_retries=3,
            retry_delay=2,
            tags=["test", "failing"]
        )
        
        # Мониторим статусы
        print("\nMonitoring task statuses...")
        for i in range(20):
            status1 = scheduler.get_task_status(task1_id)
            status2 = scheduler.get_task_status(task2_id)
            status5 = scheduler.get_task_status(task5_id)
            
            print(f"{i+1}: Task1={status1}, Task2={status2}, Task5={status5}")
            
            if i == 10:
                print("\nCancelling task 5...")
                scheduler.cancel_task(task5_id)
            
            time.sleep(1)
        
        # Получаем результаты
        print("\nGetting task results...")
        result1 = scheduler.get_task_result(task1_id)
        print(f"Task 1 result: {result1}")
        
        # Получаем статистику
        print("\nScheduler statistics:")
        stats = scheduler.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        # Ждем завершения оставшихся задач
        print("\nWaiting for remaining tasks...")
        time.sleep(10)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        # Останавливаем планировщик
        print("\nStopping scheduler...")
        scheduler.stop()
        
        # Финальная статистика
        print("\nFinal statistics:")
        stats = scheduler.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()