import xml.etree.ElementTree as ET
import lxml.etree as lxml_etree
import lxml.objectify as objectify
import io
import gzip
import zipfile
import tarfile
import os
import hashlib
import logging
import re
from typing import (
    Any, Dict, List, Optional, Union, Iterator, Tuple, 
    Callable, Generator, Set, TypeVar, Generic, BinaryIO
)
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, date
from decimal import Decimal
import csv
import json
import sqlite3
import tempfile
from pathlib import Path
import concurrent.futures
import multiprocessing
from multiprocessing import Pool, Queue, Process, Manager
import queue
import signal
import time
import psutil
from contextlib import contextmanager

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar('T')

class ProcessingMode(Enum):
    """Режимы обработки XML."""
    ITERATIVE = "iterative"        # Итеративная обработка через xml.etree
    LAZY = "lazy"                  # Ленивая загрузка через lxml
    CHUNKED = "chunked"            # Обработка чанками
    STREAMING = "streaming"        # Потоковая обработка
    PARALLEL = "parallel"          # Параллельная обработка

class CompressionType(Enum):
    """Типы сжатия файлов."""
    NONE = "none"
    GZIP = "gzip"
    ZIP = "zip"
    TAR = "tar"
    BZ2 = "bz2"

class ValidationResult(Enum):
    """Результаты валидации."""
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"
    ERROR = "error"

@dataclass
class XMLValidationError(Exception):
    """Исключение для ошибок валидации XML."""
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    severity: str = "error"
    
class XMLProcessingError(Exception):
    """Исключение для ошибок обработки XML."""
    pass

@dataclass
class XMLNodeInfo:
    """Информация о XML узле."""
    tag: str
    attributes: Dict[str, str]
    text: Optional[str] = None
    depth: int = 0
    path: str = ""
    line_number: Optional[int] = None
    parent_tag: Optional[str] = None
    namespace: Optional[str] = None

@dataclass
class XMLStats:
    """Статистика обработки XML файла."""
    total_elements: int = 0
    processed_elements: int = 0
    skipped_elements: int = 0
    failed_elements: int = 0
    total_size_bytes: int = 0
    processing_time_seconds: float = 0.0
    memory_usage_mb: float = 0.0
    compression_ratio: float = 1.0
    validation_errors: int = 0
    validation_warnings: int = 0

@dataclass
class ProcessingConfig:
    """Конфигурация обработки XML."""
    mode: ProcessingMode = ProcessingMode.ITERATIVE
    chunk_size: int = 10000
    max_memory_mb: int = 512
    encoding: str = "utf-8"
    target_elements: List[str] = field(default_factory=list)
    exclude_elements: List[str] = field(default_factory=list)
    validate_schema: bool = True
    remove_namespaces: bool = False
    normalize_text: bool = True
    skip_comments: bool = True
    skip_processing_instructions: bool = True
    timeout_seconds: int = 300
    max_file_size_gb: int = 10
    output_format: str = "json"  # json, csv, parquet, sqlite
    temp_directory: Optional[str] = None
    enable_cache: bool = False
    cache_size_mb: int = 100
    max_workers: int = None
    log_progress: bool = True
    progress_interval: int = 1000

class XMLSchemaValidator:
    """Валидатор XML схем."""
    
    def __init__(self, schema_content: Optional[str] = None):
        self.schema_content = schema_content
        self._validator = None
        
        if schema_content:
            self._init_validator()
    
    def _init_validator(self):
        """Инициализация валидатора схемы."""
        try:
            schema_root = lxml_etree.fromstring(self.schema_content.encode('utf-8'))
            schema = lxml_etree.XMLSchema(schema_root)
            self._validator = schema
        except Exception as e:
            logger.warning(f"Failed to initialize XML schema validator: {e}")
    
    def validate(self, xml_content: bytes) -> Tuple[ValidationResult, List[str]]:
        """
        Валидация XML контента.
        
        Args:
            xml_content: XML данные для валидации
            
        Returns:
            Кортеж (результат, список ошибок)
        """
        if not self._validator:
            return ValidationResult.VALID, []
        
        try:
            xml_doc = lxml_etree.fromstring(xml_content)
            self._validator.assertValid(xml_doc)
            return ValidationResult.VALID, []
        except lxml_etree.DocumentInvalid as e:
            errors = [str(error) for error in e.error_log]
            return ValidationResult.INVALID, errors
        except Exception as e:
            return ValidationResult.ERROR, [str(e)]

class XMLFileProcessor:
    """Процессор больших XML файлов."""
    
    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()
        self.stats = XMLStats()
        self._schema_validator = XMLSchemaValidator()
        self._temp_files: List[str] = []
        self._cache: Dict[str, Any] = {}
        self._setup_temp_directory()
        
        # Настройка максимального количества workers
        if self.config.max_workers is None:
            self.config.max_workers = max(1, multiprocessing.cpu_count() - 1)
    
    def _setup_temp_directory(self):
        """Настройка временной директории."""
        if self.config.temp_directory:
            temp_dir = Path(self.config.temp_directory)
            temp_dir.mkdir(parents=True, exist_ok=True)
            self._temp_dir = temp_dir
        else:
            self._temp_dir = Path(tempfile.gettempdir()) / "xml_processor"
            self._temp_dir.mkdir(parents=True, exist_ok=True)
    
    def _cleanup_temp_files(self):
        """Очистка временных файлов."""
        for temp_file in self._temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_file}: {e}")
        self._temp_files.clear()
    
    def _detect_compression(self, file_path: Union[str, Path]) -> CompressionType:
        """Определение типа сжатия файла."""
        path = Path(file_path)
        suffix = path.suffix.lower()
        
        if suffix == '.gz' or suffix == '.gzip':
            return CompressionType.GZIP
        elif suffix == '.zip':
            return CompressionType.ZIP
        elif suffix == '.tar' or suffix in ['.tar.gz', '.tgz']:
            return CompressionType.TAR
        elif suffix == '.bz2':
            return CompressionType.BZ2
        else:
            return CompressionType.NONE
    
    def _open_file(self, file_path: Union[str, Path], mode: str = 'rb') -> BinaryIO:
        """Открытие файла с учетом сжатия."""
        compression = self._detect_compression(file_path)
        
        if compression == CompressionType.GZIP:
            return gzip.open(file_path, mode)
        elif compression == CompressionType.ZIP:
            # Для ZIP файлов нужно извлечь первый файл
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                if not file_list:
                    raise XMLProcessingError("ZIP файл пуст")
                # Возвращаем первый XML файл в архиве
                return zip_ref.open(file_list[0], mode='r')
        elif compression == CompressionType.TAR:
            with tarfile.open(file_path, 'r:*') as tar_ref:
                members = [m for m in tar_ref.getmembers() if m.isfile()]
                if not members:
                    raise XMLProcessingError("TAR файл пуст")
                return tar_ref.extractfile(members[0])
        else:
            return open(file_path, mode)
    
    def _check_file_size(self, file_path: Union[str, Path]) -> bool:
        """Проверка размера файла."""
        file_size = os.path.getsize(file_path)
        max_size = self.config.max_file_size_gb * 1024 * 1024 * 1024
        
        if file_size > max_size:
            raise XMLProcessingError(
                f"Файл слишком большой: {file_size / (1024**3):.2f}GB > "
                f"{self.config.max_file_size_gb}GB"
            )
        
        self.stats.total_size_bytes = file_size
        return True
    
    def _normalize_text(self, text: str) -> str:
        """Нормализация текста."""
        if not self.config.normalize_text:
            return text
        
        # Удаление лишних пробелов и переносов строк
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        return text
    
    def _remove_namespaces(self, tag: str) -> str:
        """Удаление namespace из тега."""
        if not self.config.remove_namespaces:
            return tag
        
        if '}' in tag:
            return tag.split('}', 1)[1]
        return tag
    
    def _parse_node_info(self, element: ET.Element, depth: int = 0, path: str = "") -> XMLNodeInfo:
        """Парсинг информации об узле."""
        tag = self._remove_namespaces(element.tag)
        
        # Получение полного пути
        current_path = f"{path}/{tag}" if path else tag
        
        # Атрибуты
        attributes = {k: v for k, v in element.attrib.items()}
        
        # Текст
        text = element.text
        if text and self.config.normalize_text:
            text = self._normalize_text(text)
        
        return XMLNodeInfo(
            tag=tag,
            attributes=attributes,
            text=text,
            depth=depth,
            path=current_path,
            line_number=getattr(element, '_lineno', None),
            namespace=element.tag.split('}', 1)[0].strip('{') if '}' in element.tag else None
        )
    
    def _should_process_element(self, node_info: XMLNodeInfo) -> bool:
        """Определение, нужно ли обрабатывать элемент."""
        # Проверка исключенных элементов
        if self.config.exclude_elements:
            for pattern in self.config.exclude_elements:
                if node_info.tag == pattern or node_info.path.endswith(pattern):
                    return False
        
        # Проверка целевых элементов
        if self.config.target_elements:
            for pattern in self.config.target_elements:
                if node_info.tag == pattern or node_info.path.endswith(pattern):
                    return True
            return False
        
        return True
    
    def _stream_xml_elements(
        self, 
        file_obj: BinaryIO
    ) -> Generator[Tuple[ET.Element, XMLNodeInfo], None, None]:
        """Потоковая итерация по элементам XML."""
        context = ET.iterparse(file_obj, events=('start', 'end'))
        
        root = None
        element_stack: List[ET.Element] = []
        depth = 0
        
        for event, element in context:
            if event == 'start':
                element_stack.append(element)
                depth += 1
            elif event == 'end':
                element_stack.pop()
                depth -= 1
                
                # Пропускаем комментарии и инструкции обработки
                if self.config.skip_comments and element.tag is ET.Comment:
                    element.clear()
                    continue
                    
                if self.config.skip_processing_instructions and element.tag is ET.ProcessingInstruction:
                    element.clear()
                    continue
                
                # Получаем информацию об элементе
                node_info = self._parse_node_info(element, depth)
                
                # Проверяем, нужно ли обрабатывать элемент
                if self._should_process_element(node_info):
                    yield element, node_info
                
                # Очищаем элемент из памяти, если это не корень
                if element != root:
                    element.clear()
        
        # Освобождаем память корневого элемента
        if root:
            root.clear()
    
    def _process_chunk(
        self, 
        chunk_data: List[Tuple[ET.Element, XMLNodeInfo]],
        processor_func: Callable[[XMLNodeInfo, Dict[str, Any]], Optional[T]]
    ) -> Tuple[List[T], int, int]:
        """Обработка чанка данных."""
        processed = []
        skipped = 0
        failed = 0
        
        for element, node_info in chunk_data:
            try:
                # Вызов пользовательской функции обработки
                result = processor_func(node_info, {})
                if result is not None:
                    processed.append(result)
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"Error processing element {node_info.path}: {e}")
                failed += 1
            finally:
                # Освобождаем память
                element.clear()
        
        return processed, skipped, failed
    
    def _parallel_process(
        self,
        file_path: Union[str, Path],
        processor_func: Callable[[XMLNodeInfo, Dict[str, Any]], Optional[T]],
        output_handler: Callable[[List[T]], None]
    ) -> XMLStats:
        """Параллельная обработка XML файла."""
        start_time = time.time()
        
        # Создание очереди для чанков
        manager = Manager()
        chunk_queue = manager.Queue(maxsize=50)
        result_queue = manager.Queue()
        stop_event = manager.Event()
        
        # Функция для чтения файла и создания чанков
        def reader_process():
            try:
                with self._open_file(file_path) as file_obj:
                    chunk = []
                    for element, node_info in self._stream_xml_elements(file_obj):
                        chunk.append((element, node_info))
                        
                        if len(chunk) >= self.config.chunk_size:
                            chunk_queue.put(chunk)
                            chunk = []
                    
                    # Отправка последнего чанка
                    if chunk:
                        chunk_queue.put(chunk)
                
                # Сигнал о завершении чтения
                for _ in range(self.config.max_workers):
                    chunk_queue.put(None)
                    
            except Exception as e:
                logger.error(f"Reader process failed: {e}")
                stop_event.set()
        
        # Функция для обработки чанков
        def worker_process(worker_id: int):
            try:
                while not stop_event.is_set():
                    try:
                        chunk = chunk_queue.get(timeout=1)
                        
                        # Получение None означает завершение
                        if chunk is None:
                            break
                        
                        # Обработка чанка
                        processed, skipped, failed = self._process_chunk(chunk, processor_func)
                        
                        # Отправка результатов
                        if processed:
                            result_queue.put((worker_id, processed, skipped, failed))
                            
                    except queue.Empty:
                        continue
                        
            except Exception as e:
                logger.error(f"Worker {worker_id} failed: {e}")
                stop_event.set()
        
        # Функция для сбора результатов
        def writer_process():
            total_processed = 0
            total_skipped = 0
            total_failed = 0
            
            try:
                workers_done = 0
                while workers_done < self.config.max_workers:
                    try:
                        worker_id, processed, skipped, failed = result_queue.get(timeout=5)
                        
                        # Обработка результатов
                        output_handler(processed)
                        
                        total_processed += len(processed)
                        total_skipped += skipped
                        total_failed += failed
                        
                        # Логирование прогресса
                        if self.config.log_progress and total_processed % self.config.progress_interval == 0:
                            logger.info(f"Processed {total_processed} elements")
                            
                    except queue.Empty:
                        if stop_event.is_set():
                            break
                        continue
                
                # Обработка оставшихся результатов
                while not result_queue.empty():
                    worker_id, processed, skipped, failed = result_queue.get_nowait()
                    output_handler(processed)
                    total_processed += len(processed)
                    total_skipped += skipped
                    total_failed += failed
                    
            except Exception as e:
                logger.error(f"Writer process failed: {e}")
            
            return total_processed, total_skipped, total_failed
        
        # Запуск процессов
        reader = Process(target=reader_process)
        workers = [Process(target=worker_process, args=(i,)) 
                  for i in range(self.config.max_workers)]
        writer = Process(target=writer_process)
        
        # Запуск
        reader.start()
        for worker in workers:
            worker.start()
        writer.start()
        
        # Ожидание завершения
        reader.join()
        for worker in workers:
            worker.join()
        
        # Получение результатов от writer
        writer.join()
        
        processing_time = time.time() - start_time
        
        # Обновление статистики
        self.stats.processing_time_seconds = processing_time
        self.stats.memory_usage_mb = psutil.Process().memory_info().rss / 1024 / 1024
        
        return self.stats
    
    def process_xml(
        self,
        file_path: Union[str, Path],
        processor_func: Callable[[XMLNodeInfo, Dict[str, Any]], Optional[T]],
        output_handler: Optional[Callable[[List[T]], None]] = None,
        schema_content: Optional[str] = None
    ) -> XMLStats:
        """
        Основная функция обработки XML файла.
        
        Args:
            file_path: Путь к XML файлу
            processor_func: Функция для обработки каждого элемента
            output_handler: Функция для обработки результатов
            schema_content: Содержимое XML схемы для валидации
            
        Returns:
            Статистика обработки
        """
        start_time = time.time()
        
        try:
            # Проверка размера файла
            self._check_file_path(file_path)
            
            # Инициализация валидатора схемы
            if schema_content and self.config.validate_schema:
                self._schema_validator = XMLSchemaValidator(schema_content)
            
            # Валидация файла
            if self.config.validate_schema:
                self._validate_xml_file(file_path)
            
            # Выбор режима обработки
            if self.config.mode == ProcessingMode.PARALLEL:
                return self._parallel_process(file_path, processor_func, output_handler or self._default_output_handler)
            elif self.config.mode == ProcessingMode.STREAMING:
                return self._stream_process(file_path, processor_func, output_handler or self._default_output_handler)
            else:
                return self._iterative_process(file_path, processor_func, output_handler or self._default_output_handler)
                
        except Exception as e:
            logger.error(f"Error processing XML file: {e}")
            raise XMLProcessingError(f"Failed to process XML: {str(e)}") from e
        finally:
            # Очистка временных файлов
            self._cleanup_temp_files()
            
            # Обновление времени обработки
            self.stats.processing_time_seconds = time.time() - start_time
    
    def _check_file_path(self, file_path: Union[str, Path]):
        """Проверка пути к файлу."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not path.is_file():
            raise XMLProcessingError(f"Path is not a file: {file_path}")
        
        # Проверка размера
        self._check_file_size(path)
    
    def _validate_xml_file(self, file_path: Union[str, Path]):
        """Валидация XML файла."""
        try:
            with self._open_file(file_path, 'rb') as f:
                # Чтение первых байт для базовой валидации
                header = f.read(1024)
                f.seek(0)
                
                # Проверка, что это XML
                if b'<?xml' not in header[:100]:
                    logger.warning("File does not appear to be valid XML")
                
                # Валидация схемой если есть
                if self._schema_validator:
                    xml_content = f.read()
                    result, errors = self._schema_validator.validate(xml_content)
                    
                    if result != ValidationResult.VALID:
                        error_msg = f"XML validation failed: {errors[:5]}"
                        if len(errors) > 5:
                            error_msg += f" ... and {len(errors) - 5} more"
                        
                        if result == ValidationResult.INVALID:
                            raise XMLValidationError(error_msg)
                        else:
                            logger.warning(error_msg)
        
        except ET.ParseError as e:
            raise XMLValidationError(f"XML parse error: {str(e)}")
    
    def _iterative_process(
        self,
        file_path: Union[str, Path],
        processor_func: Callable[[XMLNodeInfo, Dict[str, Any]], Optional[T]],
        output_handler: Callable[[List[T]], None]
    ) -> XMLStats:
        """Итеративная обработка XML."""
        processed_count = 0
        skipped_count = 0
        failed_count = 0
        
        try:
            with self._open_file(file_path) as file_obj:
                for element, node_info in self._stream_xml_elements(file_obj):
                    self.stats.total_elements += 1
                    
                    try:
                        result = processor_func(node_info, {})
                        if result is not None:
                            processed_count += 1
                            output_handler([result])
                        else:
                            skipped_count += 1
                    except Exception as e:
                        logger.error(f"Error processing element: {e}")
                        failed_count += 1
                    
                    # Логирование прогресса
                    if self.config.log_progress and processed_count % self.config.progress_interval == 0:
                        logger.info(f"Processed {processed_count} elements")
                        
                    # Проверка использования памяти
                    if self._check_memory_usage():
                        logger.warning("Memory usage high, consider using chunked or streaming mode")
        
        except Exception as e:
            logger.error(f"Error during iterative processing: {e}")
            raise
        
        # Обновление статистики
        self.stats.processed_elements = processed_count
        self.stats.skipped_elements = skipped_count
        self.stats.failed_elements = failed_count
        
        return self.stats
    
    def _stream_process(
        self,
        file_path: Union[str, Path],
        processor_func: Callable[[XMLNodeInfo, Dict[str, Any]], Optional[T]],
        output_handler: Callable[[List[T]], None]
    ) -> XMLStats:
        """Потоковая обработка XML с использованием lxml."""
        processed_count = 0
        skipped_count = 0
        failed_count = 0
        
        try:
            context = lxml_etree.iterparse(
                str(file_path),
                events=('end',),
                tag=self.config.target_elements if self.config.target_elements else None,
                huge_file=True
            )
            
            for event, element in context:
                self.stats.total_elements += 1
                
                try:
                    # Преобразование в наш формат
                    node_info = XMLNodeInfo(
                        tag=self._remove_namespaces(element.tag),
                        attributes=dict(element.attrib),
                        text=self._normalize_text(element.text) if element.text else None,
                        path=element.tag
                    )
                    
                    result = processor_func(node_info, {})
                    if result is not None:
                        processed_count += 1
                        output_handler([result])
                    else:
                        skipped_count += 1
                        
                except Exception as e:
                    logger.error(f"Error processing element: {e}")
                    failed_count += 1
                finally:
                    # Освобождение памяти
                    element.clear()
                    while element.getprevious() is not None:
                        del element.getparent()[0]
                
                # Логирование прогресса
                if self.config.log_progress and processed_count % self.config.progress_interval == 0:
                    logger.info(f"Processed {processed_count} elements")
        
        except Exception as e:
            logger.error(f"Error during stream processing: {e}")
            raise
        
        # Обновление статистики
        self.stats.processed_elements = processed_count
        self.stats.skipped_elements = skipped_count
        self.stats.failed_elements = failed_count
        
        return self.stats
    
    def _default_output_handler(self, results: List[Any]) -> None:
        """Обработчик вывода по умолчанию."""
        # Просто логируем количество обработанных элементов
        if results:
            logger.debug(f"Processed batch of {len(results)} items")
    
    def _check_memory_usage(self) -> bool:
        """Проверка использования памяти."""
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        self.stats.memory_usage_mb = memory_mb
        
        return memory_mb > self.config.max_memory_mb
    
    def extract_to_json(
        self,
        file_path: Union[str, Path],
        output_path: Union[str, Path],
        elements_to_extract: List[str]
    ) -> XMLStats:
        """Извлечение данных из XML в JSON файл."""
        output_path = Path(output_path)
        
        def processor(node_info: XMLNodeInfo, context: Dict) -> Optional[Dict]:
            if node_info.tag in elements_to_extract:
                return {
                    'tag': node_info.tag,
                    'attributes': node_info.attributes,
                    'text': node_info.text,
                    'path': node_info.path,
                    'depth': node_info.depth
                }
            return None
        
        results = []
        
        def output_handler(batch: List[Dict]):
            results.extend(batch)
        
        stats = self.process_xml(file_path, processor, output_handler)
        
        # Запись в JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        return stats
    
    def extract_to_csv(
        self,
        file_path: Union[str, Path],
        output_path: Union[str, Path],
        field_mapping: Dict[str, str]
    ) -> XMLStats:
        """Извлечение данных из XML в CSV файл."""
        output_path = Path(output_path)
        
        def processor(node_info: XMLNodeInfo, context: Dict) -> Optional[Dict]:
            result = {}
            for xml_field, csv_field in field_mapping.items():
                if xml_field in node_info.attributes:
                    result[csv_field] = node_info.attributes[xml_field]
                elif xml_field == 'text' and node_info.text:
                    result[csv_field] = node_info.text
                elif xml_field == 'tag':
                    result[csv_field] = node_info.tag
            return result if result else None
        
        results = []
        
        def output_handler(batch: List[Dict]):
            results.extend(batch)
        
        stats = self.process_xml(file_path, processor, output_handler)
        
        # Запись в CSV
        if results:
            fieldnames = list(field_mapping.values())
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(results)
        
        return stats
    
    def extract_to_sqlite(
        self,
        file_path: Union[str, Path],
        db_path: Union[str, Path],
        table_name: str,
        schema: Dict[str, str]
    ) -> XMLStats:
        """Извлечение данных из XML в SQLite базу данных."""
        db_path = Path(db_path)
        
        # Создание/подключение к базе данных
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Создание таблицы
        columns = [f"{name} {type}" for name, type in schema.items()]
        create_table_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(columns)})"
        cursor.execute(create_table_sql)
        
        def processor(node_info: XMLNodeInfo, context: Dict) -> Optional[Dict]:
            # Маппинг данных на схему таблицы
            row = {}
            for column, xml_field in schema.items():
                if xml_field in node_info.attributes:
                    row[column] = node_info.attributes[xml_field]
                elif xml_field == 'text' and node_info.text:
                    row[column] = node_info.text
                elif xml_field == 'tag':
                    row[column] = node_info.tag
                elif xml_field == 'path':
                    row[column] = node_info.path
            return row if row else None
        
        def output_handler(batch: List[Dict]):
            if batch:
                columns = list(batch[0].keys())
                placeholders = ', '.join(['?' for _ in columns])
                insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                
                values = [tuple(item[col] for col in columns) for item in batch]
                cursor.executemany(insert_sql, values)
                conn.commit()
        
        try:
            stats = self.process_xml(file_path, processor, output_handler)
            return stats
        finally:
            conn.close()
    
    def analyze_xml_structure(
        self,
        file_path: Union[str, Path],
        max_depth: int = 10
    ) -> Dict[str, Any]:
        """Анализ структуры XML файла."""
        structure = {
            'root_element': None,
            'element_counts': {},
            'attribute_counts': {},
            'max_depth': 0,
            'total_elements': 0,
            'unique_elements': set(),
            'sample_data': {}
        }
        
        def processor(node_info: XMLNodeInfo, context: Dict) -> Optional[Dict]:
            # Обновление структуры
            if not structure['root_element'] and node_info.depth == 1:
                structure['root_element'] = node_info.tag
            
            structure['total_elements'] += 1
            structure['unique_elements'].add(node_info.tag)
            structure['max_depth'] = max(structure['max_depth'], node_info.depth)
            
            # Подсчет элементов
            structure['element_counts'][node_info.tag] = structure['element_counts'].get(node_info.tag, 0) + 1
            
            # Подсчет атрибутов
            for attr in node_info.attributes:
                structure['attribute_counts'][attr] = structure['attribute_counts'].get(attr, 0) + 1
            
            # Сбор примеров данных (только для первого уровня)
            if node_info.depth == 1 and node_info.tag not in structure['sample_data']:
                structure['sample_data'][node_info.tag] = {
                    'attributes': node_info.attributes,
                    'text_preview': (node_info.text[:100] + '...') if node_info.text and len(node_info.text) > 100 else node_info.text
                }
            
            return None
        
        stats = self.process_xml(file_path, processor, self._default_output_handler)
        
        structure['processing_stats'] = {
            'total_processed': stats.processed_elements,
            'processing_time': stats.processing_time_seconds,
            'file_size_mb': stats.total_size_bytes / 1024 / 1024
        }
        
        structure['unique_elements'] = list(structure['unique_elements'])
        
        return structure
    
    @contextmanager
    def timeout_context(self, timeout: int):
        """Контекстный менеджер для таймаута."""
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Processing timeout after {timeout} seconds")
        
        # Установка обработчика таймаута
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)
        
        try:
            yield
        finally:
            # Отмена таймаута
            signal.alarm(0)
    
    def __enter__(self):
        """Поддержка контекстного менеджера."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Очистка ресурсов при выходе."""
        self._cleanup_temp_files()
    
    def __del__(self):
        """Деструктор."""
        self._cleanup_temp_files()