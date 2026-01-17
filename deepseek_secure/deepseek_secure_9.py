import time
import threading
import statistics
from typing import Any, Dict, List, Optional, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
import sqlite3
from contextlib import contextmanager
import logging
from collections import deque, defaultdict
import psutil
import asyncio

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Типы метрик."""
    COUNTER = "counter"      # Только увеличивается (запросы, ошибки)
    GAUGE = "gauge"         # Может увеличиваться и уменьшаться (память, CPU)
    HISTOGRAM = "histogram" # Распределение значений (время ответа)
    SUMMARY = "summary"     # Процентили (аналогично histogram)


class AggregationMethod(str, Enum):
    """Методы агрегации метрик."""
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    LAST = "last"
    P50 = "p50"
    P95 = "p95"
    P99 = "p99"


@dataclass
class Metric:
    """Базовый класс метрики."""
    name: str
    type: MetricType
    value: float
    timestamp: datetime = field(default_factory=datetime.now)
    tags: Dict[str, str] = field(default_factory=dict)
    description: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'name': self.name,
            'type': self.type.value,
            'value': self.value,
            'timestamp': self.timestamp.isoformat(),
            'tags': self.tags,
            'description': self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Metric':
        """Десериализация из словаря."""
        return cls(
            name=data['name'],
            type=MetricType(data['type']),
            value=data['value'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            tags=data.get('tags', {}),
            description=data.get('description')
        )


@dataclass
class AggregatedMetric:
    """Агрегированная метрика."""
    name: str
    type: MetricType
    aggregation: AggregationMethod
    value: float
    timestamp: datetime
    period_seconds: int
    tags: Dict[str, str]
    sample_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'name': self.name,
            'type': self.type.value,
            'aggregation': self.aggregation.value,
            'value': self.value,
            'timestamp': self.timestamp.isoformat(),
            'period_seconds': self.period_seconds,
            'tags': self.tags,
            'sample_count': self.sample_count
        }


class MetricBuffer:
    """Буфер для временного хранения метрик."""
    
    def __init__(self, max_size: int = 10000):
        """
        Инициализация буфера.
        
        Args:
            max_size: Максимальное количество метрик в буфере
        """
        self.max_size = max_size
        self.buffer: deque[Metric] = deque(maxlen=max_size)
        self.lock = threading.RLock()
        self._dropped_metrics = 0
    
    def add(self, metric: Metric) -> bool:
        """
        Добавление метрики в буфер.
        
        Args:
            metric: Метрика для добавления
            
        Returns:
            True если успешно добавлено
        """
        with self.lock:
            if len(self.buffer) >= self.max_size:
                self._dropped_metrics += 1
                logger.warning(f"Metric buffer full, dropped {self._dropped_metrics} metrics")
                return False
            
            self.buffer.append(metric)
            return True
    
    def take_all(self) -> List[Metric]:
        """
        Извлечение всех метрик из буфера.
        
        Returns:
            Список всех метрик в буфере
        """
        with self.lock:
            metrics = list(self.buffer)
            self.buffer.clear()
            return metrics
    
    def size(self) -> int:
        """Текущий размер буфера."""
        with self.lock:
            return len(self.buffer)
    
    def get_stats(self) -> Dict[str, Any]:
        """Статистика буфера."""
        with self.lock:
            return {
                'current_size': len(self.buffer),
                'max_size': self.max_size,
                'dropped_metrics': self._dropped_metrics,
                'usage_percent': (len(self.buffer) / self.max_size) * 100
            }


class MetricStorage:
    """Постоянное хранилище метрик."""
    
    def __init__(self, db_path: str = "metrics.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица сырых метрик
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raw_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    value REAL NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    tags TEXT,
                    description TEXT
                )
            """)
            
            # Таблица агрегированных метрик
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aggregated_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    aggregation TEXT NOT NULL,
                    value REAL NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    period_seconds INTEGER NOT NULL,
                    tags TEXT,
                    sample_count INTEGER DEFAULT 0
                )
            """)
            
            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_name ON raw_metrics(name, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON raw_metrics(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_agg_metrics ON aggregated_metrics(name, aggregation, timestamp)")
            
            # Таблица для конфигурации метрик
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metric_configs (
                    name TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    retention_days INTEGER DEFAULT 30,
                    aggregation_periods TEXT,  -- JSON список периодов в секундах
                    description TEXT,
                    enabled BOOLEAN DEFAULT TRUE,
                    tags_template TEXT  -- JSON шаблон тегов
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
    
    def save_metrics(self, metrics: List[Metric]) -> int:
        """
        Сохранение метрик в БД.
        
        Args:
            metrics: Список метрик для сохранения
            
        Returns:
            Количество сохраненных метрик
        """
        if not metrics:
            return 0
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                for metric in metrics:
                    cursor.execute("""
                        INSERT INTO raw_metrics 
                        (name, type, value, timestamp, tags, description)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        metric.name,
                        metric.type.value,
                        metric.value,
                        metric.timestamp,
                        json.dumps(metric.tags) if metric.tags else None,
                        metric.description
                    ))
                
                conn.commit()
                return len(metrics)
                
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")
            return 0
    
    def save_aggregated_metric(self, metric: AggregatedMetric) -> bool:
        """Сохранение агрегированной метрики."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO aggregated_metrics 
                    (name, type, aggregation, value, timestamp, period_seconds, tags, sample_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    metric.name,
                    metric.type.value,
                    metric.aggregation.value,
                    metric.value,
                    metric.timestamp,
                    metric.period_seconds,
                    json.dumps(metric.tags) if metric.tags else None,
                    metric.sample_count
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving aggregated metric: {e}")
            return False
    
    def get_metrics(
        self,
        name: str,
        start_time: datetime,
        end_time: datetime,
        tags_filter: Optional[Dict[str, str]] = None,
        limit: int = 1000
    ) -> List[Metric]:
        """
        Получение метрик по имени и временному диапазону.
        
        Args:
            name: Имя метрики
            start_time: Начало временного диапазона
            end_time: Конец временного диапазона
            tags_filter: Фильтр по тегам
            limit: Максимальное количество записей
            
        Returns:
            Список метрик
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT * FROM raw_metrics 
                    WHERE name = ? 
                    AND timestamp BETWEEN ? AND ?
                """
                params = [name, start_time, end_time]
                
                # Добавляем фильтр по тегам если указан
                if tags_filter:
                    tag_conditions = []
                    for tag_key, tag_value in tags_filter.items():
                        tag_conditions.append(f"json_extract(tags, '$.{tag_key}') = ?")
                        params.append(tag_value)
                    
                    if tag_conditions:
                        query += " AND " + " AND ".join(tag_conditions)
                
                query += " ORDER BY timestamp ASC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                
                metrics = []
                for row in cursor.fetchall():
                    metric = Metric(
                        name=row['name'],
                        type=MetricType(row['type']),
                        value=row['value'],
                        timestamp=datetime.fromisoformat(row['timestamp']),
                        tags=json.loads(row['tags']) if row['tags'] else {},
                        description=row['description']
                    )
                    metrics.append(metric)
                
                return metrics
                
        except Exception as e:
            logger.error(f"Error getting metrics: {e}")
            return []
    
    def get_aggregated_metrics(
        self,
        name: str,
        aggregation: AggregationMethod,
        start_time: datetime,
        end_time: datetime,
        period_seconds: Optional[int] = None
    ) -> List[AggregatedMetric]:
        """
        Получение агрегированных метрик.
        
        Args:
            name: Имя метрики
            aggregation: Метод агрегации
            start_time: Начало временного диапазона
            end_time: Конец временного диапазона
            period_seconds: Период агрегации
            
        Returns:
            Список агрегированных метрик
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT * FROM aggregated_metrics 
                    WHERE name = ? 
                    AND aggregation = ?
                    AND timestamp BETWEEN ? AND ?
                """
                params = [name, aggregation.value, start_time, end_time]
                
                if period_seconds:
                    query += " AND period_seconds = ?"
                    params.append(period_seconds)
                
                query += " ORDER BY timestamp ASC"
                
                cursor.execute(query, params)
                
                metrics = []
                for row in cursor.fetchall():
                    metric = AggregatedMetric(
                        name=row['name'],
                        type=MetricType(row['type']),
                        aggregation=AggregationMethod(row['aggregation']),
                        value=row['value'],
                        timestamp=datetime.fromisoformat(row['timestamp']),
                        period_seconds=row['period_seconds'],
                        tags=json.loads(row['tags']) if row['tags'] else {},
                        sample_count=row['sample_count']
                    )
                    metrics.append(metric)
                
                return metrics
                
        except Exception as e:
            logger.error(f"Error getting aggregated metrics: {e}")
            return []
    
    def cleanup_old_metrics(self, retention_days: int = 30) -> int:
        """
        Очистка старых метрик.
        
        Args:
            retention_days: Количество дней хранения
            
        Returns:
            Количество удаленных записей
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Удаляем старые сырые метрики
                cursor.execute(
                    "DELETE FROM raw_metrics WHERE timestamp < ?",
                    (cutoff_date,)
                )
                raw_deleted = cursor.rowcount
                
                # Удаляем старые агрегированные метрики
                cursor.execute(
                    "DELETE FROM aggregated_metrics WHERE timestamp < ?",
                    (cutoff_date,)
                )
                agg_deleted = cursor.rowcount
                
                conn.commit()
                
                total_deleted = raw_deleted + agg_deleted
                if total_deleted > 0:
                    logger.info(f"Cleaned up {total_deleted} old metrics (raw: {raw_deleted}, agg: {agg_deleted})")
                
                return total_deleted
                
        except Exception as e:
            logger.error(f"Error cleaning up old metrics: {e}")
            return 0


class MetricAggregator:
    """Агрегатор метрик."""
    
    def __init__(self, storage: MetricStorage):
        self.storage = storage
        self.aggregation_periods = [60, 300, 3600]  # 1 мин, 5 мин, 1 час
    
    def aggregate_metrics(self, metrics: List[Metric], period_seconds: int) -> List[AggregatedMetric]:
        """
        Агрегация метрик за период.
        
        Args:
            metrics: Список метрик для агрегации
            period_seconds: Период агрегации в секундах
            
        Returns:
            Список агрегированных метрик
        """
        if not metrics:
            return []
        
        # Группируем метрики по имени и тегам
        grouped_metrics: Dict[tuple, List[Metric]] = defaultdict(list)
        
        for metric in metrics:
            # Создаем ключ группировки: (name, json(tags))
            tags_key = json.dumps(metric.tags, sort_keys=True)
            group_key = (metric.name, tags_key)
            grouped_metrics[group_key].append(metric)
        
        aggregated = []
        now = datetime.now()
        
        for (name, tags_key), metric_list in grouped_metrics.items():
            tags = json.loads(tags_key)
            values = [m.value for m in metric_list]
            
            # Разные агрегации для разных типов метрик
            if metric_list[0].type == MetricType.COUNTER:
                # Для счетчиков считаем сумму
                agg_value = sum(values)
                aggregated.append(AggregatedMetric(
                    name=name,
                    type=MetricType.COUNTER,
                    aggregation=AggregationMethod.SUM,
                    value=agg_value,
                    timestamp=now,
                    period_seconds=period_seconds,
                    tags=tags,
                    sample_count=len(values)
                ))
            
            elif metric_list[0].type == MetricType.GAUGE:
                # Для gauge считаем среднее
                agg_value = statistics.mean(values) if values else 0
                aggregated.append(AggregatedMetric(
                    name=name,
                    type=MetricType.GAUGE,
                    aggregation=AggregationMethod.AVG,
                    value=agg_value,
                    timestamp=now,
                    period_seconds=period_seconds,
                    tags=tags,
                    sample_count=len(values)
                ))
                
                # Также сохраняем min и max
                aggregated.append(AggregatedMetric(
                    name=name,
                    type=MetricType.GAUGE,
                    aggregation=AggregationMethod.MIN,
                    value=min(values) if values else 0,
                    timestamp=now,
                    period_seconds=period_seconds,
                    tags=tags,
                    sample_count=len(values)
                ))
                
                aggregated.append(AggregatedMetric(
                    name=name,
                    type=MetricType.GAUGE,
                    aggregation=AggregationMethod.MAX,
                    value=max(values) if values else 0,
                    timestamp=now,
                    period_seconds=period_seconds,
                    tags=tags,
                    sample_count=len(values)
                ))
            
            elif metric_list[0].type in [MetricType.HISTOGRAM, MetricType.SUMMARY]:
                # Для гистограмм и summary считаем процентили
                if len(values) >= 5:  # Минимум 5 значений для процентилей
                    aggregated.append(AggregatedMetric(
                        name=name,
                        type=metric_list[0].type,
                        aggregation=AggregationMethod.P50,
                        value=statistics.quantiles(values, n=100)[49] if len(values) >= 100 else statistics.median(values),
                        timestamp=now,
                        period_seconds=period_seconds,
                        tags=tags,
                        sample_count=len(values)
                    ))
                    
                    aggregated.append(AggregatedMetric(
                        name=name,
                        type=metric_list[0].type,
                        aggregation=AggregationMethod.P95,
                        value=statistics.quantiles(values, n=100)[94] if len(values) >= 100 else max(values),
                        timestamp=now,
                        period_seconds=period_seconds,
                        tags=tags,
                        sample_count=len(values)
                    ))
                    
                    aggregated.append(AggregatedMetric(
                        name=name,
                        type=metric_list[0].type,
                        aggregation=AggregationMethod.P99,
                        value=statistics.quantiles(values, n=100)[98] if len(values) >= 100 else max(values),
                        timestamp=now,
                        period_seconds=period_seconds,
                        tags=tags,
                        sample_count=len(values)
                    ))
                
                # Также считаем среднее
                aggregated.append(AggregatedMetric(
                    name=name,
                    type=metric_list[0].type,
                    aggregation=AggregationMethod.AVG,
                    value=statistics.mean(values) if values else 0,
                    timestamp=now,
                    period_seconds=period_seconds,
                    tags=tags,
                    sample_count=len(values)
                ))
        
        return aggregated


class SystemMetricsCollector:
    """Сборщик системных метрик."""
    
    def __init__(self):
        self.last_cpu_times = psutil.cpu_times()
        self.last_net_io = psutil.net_io_counters()
        self.last_disk_io = psutil.disk_io_counters()
    
    def collect(self) -> List[Metric]:
        """
        Сбор системных метрик.
        
        Returns:
            Список системных метрик
        """
        metrics = []
        timestamp = datetime.now()
        
        try:
            # CPU метрики
            cpu_percent = psutil.cpu_percent(interval=0.1)
            metrics.append(Metric(
                name="system.cpu.usage",
                type=MetricType.GAUGE,
                value=cpu_percent,
                timestamp=timestamp,
                tags={"type": "percent"},
                description="CPU usage percentage"
            ))
            
            # Память
            memory = psutil.virtual_memory()
            metrics.append(Metric(
                name="system.memory.usage",
                type=MetricType.GAUGE,
                value=memory.percent,
                timestamp=timestamp,
                tags={"type": "percent"},
                description="Memory usage percentage"
            ))
            
            metrics.append(Metric(
                name="system.memory.used",
                type=MetricType.GAUGE,
                value=memory.used / (1024 ** 3),  # GB
                timestamp=timestamp,
                tags={"type": "gb"},
                description="Used memory in GB"
            ))
            
            metrics.append(Metric(
                name="system.memory.available",
                type=MetricType.GAUGE,
                value=memory.available / (1024 ** 3),  # GB
                timestamp=timestamp,
                tags={"type": "gb"},
                description="Available memory in GB"
            ))
            
            # Диск
            disk = psutil.disk_usage('/')
            metrics.append(Metric(
                name="system.disk.usage",
                type=MetricType.GAUGE,
                value=disk.percent,
                timestamp=timestamp,
                tags={"mount": "/"},
                description="Disk usage percentage"
            ))
            
            # Сетевой трафик
            net_io = psutil.net_io_counters()
            if self.last_net_io:
                bytes_sent = net_io.bytes_sent - self.last_net_io.bytes_sent
                bytes_recv = net_io.bytes_recv - self.last_net_io.bytes_recv
                
                metrics.append(Metric(
                    name="system.network.bytes_sent",
                    type=MetricType.COUNTER,
                    value=bytes_sent,
                    timestamp=timestamp,
                    tags={"direction": "out"},
                    description="Bytes sent since last collection"
                ))
                
                metrics.append(Metric(
                    name="system.network.bytes_received",
                    type=MetricType.COUNTER,
                    value=bytes_recv,
                    timestamp=timestamp,
                    tags={"direction": "in"},
                    description="Bytes received since last collection"
                ))
            
            self.last_net_io = net_io
            
            # Процессы
            metrics.append(Metric(
                name="system.processes.count",
                type=MetricType.GAUGE,
                value=len(psutil.pids()),
                timestamp=timestamp,
                description="Number of running processes"
            ))
            
            # Load average
            load_avg = psutil.getloadavg()
            metrics.append(Metric(
                name="system.load.1min",
                type=MetricType.GAUGE,
                value=load_avg[0],
                timestamp=timestamp,
                description="1-minute load average"
            ))
            
            metrics.append(Metric(
                name="system.load.5min",
                type=MetricType.GAUGE,
                value=load_avg[1],
                timestamp=timestamp,
                description="5-minute load average"
            ))
            
            metrics.append(Metric(
                name="system.load.15min",
                type=MetricType.GAUGE,
                value=load_avg[2],
                timestamp=timestamp,
                description="15-minute load average"
            ))
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
        
        return metrics


class MetricsCollector:
    """Основной класс сбора метрик."""
    
    def __init__(
        self,
        storage: Optional[MetricStorage] = None,
        buffer_size: int = 10000,
        flush_interval: int = 30
    ):
        """
        Инициализация сборщика метрик.
        
        Args:
            storage: Хранилище метрик
            buffer_size: Размер буфера
            flush_interval: Интервал сброса в секундах
        """
        self.storage = storage or MetricStorage()
        self.aggregator = MetricAggregator(self.storage)
        self.buffer = MetricBuffer(max_size=buffer_size)
        self.system_collector = SystemMetricsCollector()
        
        self.flush_interval = flush_interval
        self._running = False
        self._flush_thread: Optional[threading.Thread] = None
        self._system_collect_thread: Optional[threading.Thread] = None
        
        # Регистры для счетчиков
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
    
    def counter(self, name: str, value: float = 1, tags: Optional[Dict[str, str]] = None,
                description: Optional[str] = None) -> None:
        """
        Инкремент счетчика.
        
        Args:
            name: Имя счетчика
            value: Значение для инкремента
            tags: Теги метрики
            description: Описание метрики
        """
        metric = Metric(
            name=name,
            type=MetricType.COUNTER,
            value=value,
            tags=tags or {},
            description=description
        )
        self.buffer.add(metric)
    
    def gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None,
              description: Optional[str] = None) -> None:
        """
        Установка значения gauge.
        
        Args:
            name: Имя gauge
            value: Значение
            tags: Теги метрики
            description: Описание метрики
        """
        metric = Metric(
            name=name,
            type=MetricType.GAUGE,
            value=value,
            tags=tags or {},
            description=description
        )
        self.buffer.add(metric)
    
    def histogram(self, name: str, value: float, tags: Optional[Dict[str, str]] = None,
                  description: Optional[str] = None) -> None:
        """
        Добавление значения в гистограмму.
        
        Args:
            name: Имя гистограммы
            value: Значение
            tags: Теги метрики
            description: Описание метрики
        """
        metric = Metric(
            name=name,
            type=MetricType.HISTOGRAM,
            value=value,
            tags=tags or {},
            description=description
        )
        self.buffer.add(metric)
    
    def timeit(self, name: str, tags: Optional[Dict[str, str]] = None):
        """
        Контекстный менеджер для измерения времени выполнения.
        
        Args:
            name: Имя метрики времени
            tags: Теги метрики
        """
        class Timer:
            def __init__(self, collector, name, tags):
                self.collector = collector
                self.name = name
                self.tags = tags or {}
                self.start_time = None
            
            def __enter__(self):
                self.start_time = time.time()
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                elapsed = time.time() - self.start_time
                self.collector.histogram(
                    name=self.name,
                    value=elapsed * 1000,  # Конвертируем в миллисекунды
                    tags=self.tags,
                    description="Execution time in milliseconds"
                )
        
        return Timer(self, name, tags)
    
    def _flush_buffer(self):
        """Сброс буфера в хранилище."""
        metrics = self.buffer.take_all()
        if not metrics:
            return
        
        try:
            # Сохраняем сырые метрики
            saved = self.storage.save_metrics(metrics)
            if saved > 0:
                logger.debug(f"Flushed {saved} metrics to storage")
            
            # Агрегируем метрики для разных периодов
            for period in self.aggregator.aggregation_periods:
                aggregated = self.aggregator.aggregate_metrics(metrics, period)
                
                for agg_metric in aggregated:
                    self.storage.save_aggregated_metric(agg_metric)
                
                if aggregated:
                    logger.debug(f"Aggregated {len(aggregated)} metrics for {period}s period")
                    
        except Exception as e:
            logger.error(f"Error flushing metrics buffer: {e}")
    
    def _flush_loop(self):
        """Цикл сброса буфера."""
        logger.info("Metrics flush loop started")
        
        while self._running:
            try:
                self._flush_buffer()
                time.sleep(self.flush_interval)
                
            except Exception as e:
                logger.error(f"Error in flush loop: {e}")
                time.sleep(5)
    
    def _system_collect_loop(self):
        """Цикл сбора системных метрик."""
        logger.info("System metrics collection loop started")
        
        while self._running:
            try:
                system_metrics = self.system_collector.collect()
                for metric in system_metrics:
                    self.buffer.add(metric)
                
                time.sleep(10)  # Собираем системные метрики каждые 10 секунд
                
            except Exception as e:
                logger.error(f"Error collecting system metrics: {e}")
                time.sleep(30)
    
    def start(self):
        """Запуск сборщика метрик."""
        if self._running:
            logger.warning("Metrics collector is already running")
            return
        
        self._running = True
        
        # Запускаем поток сброса буфера
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            name="MetricsFlushThread",
            daemon=True
        )
        self._flush_thread.start()
        
        # Запускаем поток сбора системных метрик
        self._system_collect_thread = threading.Thread(
            target=self._system_collect_loop,
            name="SystemMetricsThread",
            daemon=True
        )
        self._system_collect_thread.start()
        
        logger.info("Metrics collector started")
    
    def stop(self):
        """Остановка сборщика метрик."""
        self._running = False
        
        # Сбрасываем оставшиеся метрики
        self._flush_buffer()
        
        # Очищаем старые метрики
        self.storage.cleanup_old_metrics()
        
        logger.info("Metrics collector stopped")
    
    def get_metrics(
        self,
        name: str,
        start_time: datetime,
        end_time: datetime,
        tags_filter: Optional[Dict[str, str]] = None
    ) -> List[Metric]:
        """
        Получение метрик из хранилища.
        
        Args:
            name: Имя метрики
            start_time: Начало периода
            end_time: Конец периода
            tags_filter: Фильтр по тегам
            
        Returns:
            Список метрик
        """
        return self.storage.get_metrics(name, start_time, end_time, tags_filter)
    
    def get_aggregated_metrics(
        self,
        name: str,
        aggregation: AggregationMethod,
        start_time: datetime,
        end_time: datetime,
        period_seconds: Optional[int] = None
    ) -> List[AggregatedMetric]:
        """
        Получение агрегированных метрик.
        
        Args:
            name: Имя метрики
            aggregation: Метод агрегации
            start_time: Начало периода
            end_time: Конец периода
            period_seconds: Период агрегации
            
        Returns:
            Список агрегированных метрик
        """
        return self.storage.get_aggregated_metrics(
            name, aggregation, start_time, end_time, period_seconds
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики сборщика.
        
        Returns:
            Словарь со статистикой
        """
        buffer_stats = self.buffer.get_stats()
        return {
            'buffer': buffer_stats,
            'flush_interval': self.flush_interval,
            'running': self._running
        }


# --- Пример использования ---
def example_application_logic(collector: MetricsCollector):
    """Пример использования метрик в приложении."""
    
    # Счетчик запросов
    collector.counter(
        name="app.requests",
        tags={"endpoint": "/api/users", "method": "GET"},
        description="Total API requests"
    )
    
    # Gauge для активных соединений
    collector.gauge(
        name="app.connections.active",
        value=42,
        tags={"type": "websocket"},
        description="Active WebSocket connections"
    )
    
    # Измерение времени выполнения с помощью timeit
    with collector.timeit("app.request.duration", tags={"endpoint": "/api/users"}):
        # Имитация работы
        time.sleep(0.1)
    
    # Гистограмма для размера ответа
    response_size = 2048  # bytes
    collector.histogram(
        name="app.response.size",
        value=response_size,
        tags={"endpoint": "/api/users"},
        description="Response size in bytes"
    )
    
    # Ошибки
    collector.counter(
        name="app.errors",
        value=1,
        tags={"type": "validation", "endpoint": "/api/users"},
        description="Application errors"
    )


def main():
    """Демонстрация работы сборщика метрик."""
    print("=== Metrics Collector Demo ===")
    
    # Создаем сборщик
    collector = MetricsCollector(flush_interval=5)
    
    try:
        # Запускаем сборщик
        collector.start()
        
        print("Collecting metrics for 30 seconds...")
        print("Press Ctrl+C to stop early")
        
        # Собираем метрики приложения
        for i in range(30):
            example_application_logic(collector)
            
            # Показываем статистику каждые 5 секунд
            if i % 5 == 0:
                stats = collector.get_stats()
                buffer_usage = stats['buffer']['usage_percent']
                print(f"Second {i}: Buffer usage: {buffer_usage:.1f}%")
            
            time.sleep(1)
        
        # Получаем метрики из хранилища
        print("\nRetrieving collected metrics...")
        
        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=60)
        
        # Сырые метрики
        requests = collector.get_metrics(
            name="app.requests",
            start_time=start_time,
            end_time=end_time,
            tags_filter={"endpoint": "/api/users"}
        )
        
        print(f"Total requests recorded: {len(requests)}")
        if requests:
            total_requests = sum(m.value for m in requests)
            print(f"Total request count: {total_requests}")
        
        # Агрегированные метрики
        agg_metrics = collector.get_aggregated_metrics(
            name="app.request.duration",
            aggregation=AggregationMethod.P95,
            start_time=start_time,
            end_time=end_time,
            period_seconds=60
        )
        
        if agg_metrics:
            print(f"P95 response time: {agg_metrics[0].value:.2f} ms")
        
        # Статистика сборщика
        print("\nCollector statistics:")
        stats = collector.get_stats()
        for key, value in stats.items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for k, v in value.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  {key}: {value}")
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        # Останавливаем сборщик
        print("\nStopping metrics collector...")
        collector.stop()
        
        # Очищаем старые метрики
        collector.storage.cleanup_old_metrics(retention_days=1)
        
        print("Demo completed")


if __name__ == "__main__":
    main()