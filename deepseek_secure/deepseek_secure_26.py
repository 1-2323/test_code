import asyncio
import json
from typing import Any, Dict, Optional, Callable
from datetime import datetime
from enum import Enum
import redis.asyncio as redis
from dataclasses import dataclass
import pickle

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class AsyncTask:
    """Асинхронная задача."""
    id: str
    func_name: str
    args: tuple
    kwargs: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = None
    result: Any = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

class AsyncTaskQueue:
    """Очередь асинхронных задач."""
    
    def __init__(self, redis_url: str = "redis://localhost"):
        self.redis = redis.from_url(redis_url)
        self.task_registry: Dict[str, Callable] = {}
    
    def register_task(self, func: Callable):
        """Регистрация функции как задачи."""
        self.task_registry[func.__name__] = func
        return func
    
    async def enqueue(self, func_name: str, *args, **kwargs) -> str:
        """Добавление задачи в очередь."""
        import uuid
        task_id = str(uuid.uuid4())
        
        task = AsyncTask(
            id=task_id,
            func_name=func_name,
            args=args,
            kwargs=kwargs
        )
        
        # Сохраняем задачу
        await self.redis.setex(
            f"task:{task_id}",
            3600,
            pickle.dumps(task)
        )
        
        # Добавляем в очередь
        await self.redis.lpush("task_queue", task_id)
        
        return task_id
    
    async def process_tasks(self, num_workers: int = 4):
        """Обработка задач воркерами."""
        workers = []
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            workers.append(worker)
        
        await asyncio.gather(*workers)
    
    async def _worker(self, worker_id: str):
        """Воркер для обработки задач."""
        while True:
            try:
                # Получаем задачу из очереди
                task_id = await self.redis.brpop("task_queue", timeout=1)
                if not task_id:
                    continue
                
                task_id = task_id[1].decode()
                
                # Загружаем задачу
                task_data = await self.redis.get(f"task:{task_id}")
                if not task_data:
                    continue
                
                task = pickle.loads(task_data)
                task.status = TaskStatus.PROCESSING
                await self._save_task(task)
                
                try:
                    # Выполняем задачу
                    func = self.task_registry.get(task.func_name)
                    if func:
                        result = await func(*task.args, **task.kwargs)
                        task.status = TaskStatus.COMPLETED
                        task.result = result
                    else:
                        raise ValueError(f"Function {task.func_name} not found")
                
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                
                await self._save_task(task)
                
            except Exception as e:
                print(f"Worker error: {e}")
                await asyncio.sleep(1)
    
    async def _save_task(self, task: AsyncTask):
        """Сохранение задачи."""
        await self.redis.setex(
            f"task:{task.id}",
            3600,
            pickle.dumps(task)
        )
    
    async def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """Получение задачи по ID."""
        data = await self.redis.get(f"task:{task_id}")
        if data:
            return pickle.loads(data)
        return None