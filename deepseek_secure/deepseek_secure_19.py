import logging
import json
import sys
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum
import traceback
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import threading

class LogLevel(str, Enum):
    """Уровни логгирования."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

@dataclass
class LogEntry:
    """Структурированная запись лога."""
    timestamp: str
    level: LogLevel
    message: str
    logger: str
    module: str
    function: str
    line: int
    thread: str
    process: int
    extra: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь."""
        data = asdict(self)
        if self.extra:
            data.update(self.extra)
        return data
    
    def to_json(self) -> str:
        """Сериализация в JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

class StructuredFormatter(logging.Formatter):
    """Форматтер структурированных логов."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Форматирование записи лога."""
        log_entry = LogEntry(
            timestamp=datetime.utcnow().isoformat() + "Z",
            level=LogLevel(record.levelname),
            message=record.getMessage(),
            logger=record.name,
            module=record.module,
            function=record.funcName,
            line=record.lineno,
            thread=record.threadName,
            process=record.process,
            extra=getattr(record, 'extra', {})
        )
        
        # Добавляем исключение если есть
        if record.exc_info:
            log_entry.extra['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        return log_entry.to_json()

class ContextLogger:
    """Логгер с контекстом."""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.context: Dict[str, Any] = {}
        self.local = threading.local()
    
    def _get_context(self) -> Dict[str, Any]:
        """Получение текущего контекста."""
        if not hasattr(self.local, 'context_stack'):
            self.local.context_stack = []
        
        context = self.context.copy()
        for ctx in self.local.context_stack:
            context.update(ctx)
        
        return context
    
    @contextmanager
    def context(self, **kwargs):
        """Контекстный менеджер для добавления полей."""
        if not hasattr(self.local, 'context_stack'):
            self.local.context_stack = []
        
        self.local.context_stack.append(kwargs)
        try:
            yield
        finally:
            self.local.context_stack.pop()
    
    def log(self, level: LogLevel, message: str, **extra):
        """Запись лога с контекстом."""
        context = self._get_context()
        context.update(extra)
        
        extra_data = {'extra': context}
        log_method = getattr(self.logger, level.value.lower())
        log_method(message, extra=extra_data)
    
    def debug(self, message: str, **extra):
        self.log(LogLevel.DEBUG, message, **extra)
    
    def info(self, message: str, **extra):
        self.log(LogLevel.INFO, message, **extra)
    
    def warning(self, message: str, **extra):
        self.log(LogLevel.WARNING, message, **extra)
    
    def error(self, message: str, **extra):
        self.log(LogLevel.ERROR, message, **extra)
    
    def critical(self, message: str, **extra):
        self.log(LogLevel.CRITICAL, message, **extra)
    
    def exception(self, message: str, exc: Exception, **extra):
        """Логгирование исключения."""
        self.error(message, exception_type=type(exc).__name__,
                   exception_message=str(exc), **extra)

class LogManager:
    """Менеджер логгирования."""
    
    def __init__(self):
        self.loggers: Dict[str, ContextLogger] = {}
    
    def setup_logging(self, level: LogLevel = LogLevel.INFO,
                     log_file: Optional[str] = None):
        """Настройка логгирования."""
        # Создаем корневой логгер
        root_logger = logging.getLogger()
        root_logger.setLevel(level.value)
        
        # Удаляем существующие обработчики
        root_logger.handlers.clear()
        
        # Форматтер
        formatter = StructuredFormatter()
        
        # Консольный обработчик
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # Файловый обработчик если указан
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
    
    def get_logger(self, name: str) -> ContextLogger:
        """Получение логгера по имени."""
        if name not in self.loggers:
            self.loggers[name] = ContextLogger(name)
        return self.loggers[name]
    
    @contextmanager
    def request_context(self, request_id: str, **kwargs):
        """Контекст для запроса."""
        logger = self.get_logger("request")
        with logger.context(request_id=request_id, **kwargs):
            yield logger