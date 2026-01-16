import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from contextlib import contextmanager
import tracemalloc
import time
import os
import logging
import tempfile
from pathlib import Path
import resource
import sys

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class XMLProcessingError(Exception):
    """Исключение при обработке XML"""
    pass


class ResourceLimitExceededError(XMLProcessingError):
    """Исключение при превышении лимитов ресурсов"""
    pass


@dataclass
class ProcessingLimits:
    """Лимиты обработки XML файлов"""
    max_file_size_mb: int = 100  # Максимальный размер файла в MB
    max_processing_time_sec: int = 30  # Максимальное время обработки в секундах
    max_memory_mb: int = 512  # Максимальное использование памяти в MB
    max_elements: int = 1000000  # Максимальное количество элементов


@dataclass
class ProcessingStats:
    """Статистика обработки файла"""
    file_size_mb: float
    processing_time_sec: float
    memory_used_mb: float
    elements_processed: int
    is_success: bool
    error_message: Optional[str] = None


class SecureXMLProcessor:
    """
    Безопасный процессор XML-отчетов с жесткими лимитами ресурсов
    """
    
    def __init__(self, limits: Optional[ProcessingLimits] = None):
        """
        Инициализация процессора XML
        
        Args:
            limits: лимиты обработки (если None, используются значения по умолчанию)
        """
        self.limits = limits or ProcessingLimits()
        self.current_stats: Optional[ProcessingStats] = None
        
    def process_xml_file(self, file_path: str) -> Dict[str, Any]:
        """
        Обработка XML файла с контролем ресурсов
        
        Args:
            file_path: путь к XML файлу
            
        Returns:
            Результат обработки в виде словаря
            
        Raises:
            ResourceLimitExceededError: если превышены лимиты ресурсов
            XMLProcessingError: если произошла ошибка обработки
        """
        start_time = time.time()
        start_memory = self._get_memory_usage()
        
        try:
            # Проверка размера файла
            self._validate_file_size(file_path)
            
            # Установка лимитов
            self._set_resource_limits()
            
            # Обработка с таймаутом
            result = self._process_with_timeout(file_path, start_time)
            
            # Сбор статистики
            self._collect_stats(file_path, start_time, start_memory, True)
            
            return result
            
        except ResourceLimitExceededError:
            # Перевыбрасываем исключения лимитов
            raise
        except Exception as e:
            # Сбор статистики при ошибке
            self._collect_stats(file_path, start_time, start_memory, False, str(e))
            raise XMLProcessingError(f"Ошибка обработки XML: {e}")
    
    def _validate_file_size(self, file_path: str) -> None:
        """
        Проверка размера файла
        
        Args:
            file_path: путь к файлу
            
        Raises:
            ResourceLimitExceededError: если размер файла превышает лимит
        """
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)
        
        if file_size_mb > self.limits.max_file_size_mb:
            error_msg = (f"Размер файла ({file_size_mb:.2f} MB) превышает "
                        f"максимально допустимый ({self.limits.max_file_size_mb} MB)")
            logger.error(error_msg)
            raise ResourceLimitExceededError(error_msg)
        
        logger.info(f"Размер файла: {file_size_mb:.2f} MB")
    
    def _set_resource_limits(self) -> None:
        """
        Установка лимитов использования ресурсов
        """
        try:
            # Установка лимита памяти (только для Unix-систем)
            if hasattr(resource, 'RLIMIT_AS'):
                max_memory_bytes = self.limits.max_memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, 
                                 (max_memory_bytes, max_memory_bytes))
        except (AttributeError, ValueError) as e:
            logger.warning(f"Не удалось установить лимиты памяти: {e}")
    
    def _process_with_timeout(self, file_path: str, start_time: float) -> Dict[str, Any]:
        """
        Обработка файла с контролем времени
        
        Args:
            file_path: путь к файлу
            start_time: время начала обработки
            
        Returns:
            Результат обработки
            
        Raises:
            ResourceLimitExceededError: если превышено время обработки
        """
        # Итеративный парсинг для контроля памяти
        result = {
            "root_tag": None,
            "elements_count": 0,
            "attributes_count": 0,
            "data": []
        }
        
        try:
            # Используем итеративный парсинг для контроля памяти
            for event, elem in ET.iterparse(file_path, events=('start', 'end')):
                # Проверка времени выполнения
                current_time = time.time()
                if current_time - start_time > self.limits.max_processing_time_sec:
                    error_msg = (f"Превышено время обработки "
                                f"({self.limits.max_processing_time_sec} сек)")
                    raise ResourceLimitExceededError(error_msg)
                
                # Проверка количества элементов
                if result["elements_count"] > self.limits.max_elements:
                    error_msg = (f"Превышено максимальное количество элементов "
                                f"({self.limits.max_elements})")
                    raise ResourceLimitExceededError(error_msg)
                
                if event == 'start':
                    if result["root_tag"] is None:
                        result["root_tag"] = elem.tag
                    result["elements_count"] += 1
                    result["attributes_count"] += len(elem.attrib)
                    
                    # Извлекаем данные (ограниченное количество для контроля памяти)
                    if result["elements_count"] <= 1000:  # Сохраняем только первые 1000 элементов
                        element_data = {
                            "tag": elem.tag,
                            "attributes": elem.attrib,
                            "text": elem.text[:100] if elem.text else None  # Ограничиваем текст
                        }
                        result["data"].append(element_data)
                
                # Очищаем элемент из памяти после обработки
                if event == 'end':
                    elem.clear()
                    
                # Периодическая проверка использования памяти
                if result["elements_count"] % 10000 == 0:
                    self._check_memory_usage(start_time)
            
            return result
            
        except ET.ParseError as e:
            raise XMLProcessingError(f"Ошибка парсинга XML: {e}")
    
    def _check_memory_usage(self, start_time: float) -> None:
        """
        Проверка использования памяти и времени
        
        Args:
            start_time: время начала обработки
            
        Raises:
            ResourceLimitExceededError: если превышены лимиты
        """
        # Проверка времени
        current_time = time.time()
        if current_time - start_time > self.limits.max_processing_time_sec:
            error_msg = f"Превышено время обработки"
            raise ResourceLimitExceededError(error_msg)
        
        # Проверка памяти
        memory_usage = self._get_memory_usage()
        if memory_usage > self.limits.max_memory_mb:
            error_msg = (f"Превышено использование памяти "
                        f"({memory_usage:.2f} MB > {self.limits.max_memory_mb} MB)")
            raise ResourceLimitExceededError(error_msg)
    
    def _get_memory_usage(self) -> float:
        """
        Получение текущего использования памяти в MB
        
        Returns:
            Использование памяти в MB
        """
        try:
            # Используем resource для Unix или psutil для кроссплатформенности
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            # Фолбэк на простую реализацию
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    
    def _collect_stats(self, file_path: str, start_time: float, 
                      start_memory: float, is_success: bool, 
                      error_message: Optional[str] = None) -> None:
        """
        Сбор статистики обработки
        
        Args:
            file_path: путь к файлу
            start_time: время начала обработки
            start_memory: использование памяти в начале
            is_success: успешна ли обработка
            error_message: сообщение об ошибке (если есть)
        """
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        processing_time = time.time() - start_time
        memory_used = self._get_memory_usage() - start_memory
        
        self.current_stats = ProcessingStats(
            file_size_mb=file_size,
            processing_time_sec=processing_time,
            memory_used_mb=memory_used,
            elements_processed=getattr(self, '_elements_processed', 0),
            is_success=is_success,
            error_message=error_message
        )
        
        logger.info(f"Статистика обработки: {self.current_stats}")


# Пример использования
def main():
    """Пример использования безопасного процессора XML"""
    
    # Создаем тестовый XML файл
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
        # Генерируем большой XML для теста
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<report>\n')
        for i in range(10000):
            f.write(f'  <record id="{i}">\n')
            f.write(f'    <value>Data {i}</value>\n')
            f.write('  </record>\n')
        f.write('</report>\n')
        temp_file = f.name
    
    try:
        # Инициализация процессора с лимитами
        limits = ProcessingLimits(
            max_file_size_mb=10,
            max_processing_time_sec=10,
            max_memory_mb=100,
            max_elements=20000
        )
        
        processor = SecureXMLProcessor(limits)
        
        # Обработка файла
        result = processor.process_xml_file(temp_file)
        
        print(f"Обработка завершена успешно")
        print(f"Корневой тег: {result['root_tag']}")
        print(f"Обработано элементов: {result['elements_count']}")
        print(f"Найдено атрибутов: {result['attributes_count']}")
        
    except ResourceLimitExceededError as e:
        print(f"Превышены лимиты ресурсов: {e}")
    except XMLProcessingError as e:
        print(f"Ошибка обработки XML: {e}")
    finally:
        # Удаляем временный файл
        if os.path.exists(temp_file):
            os.unlink(temp_file)


if __name__ == "__main__":
    main()