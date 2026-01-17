import lxml.etree as etree
import psutil
import os
import signal
import time
from typing import Final, Generator

# --- Настройки безопасности ---
MAX_FILE_SIZE: Final[int] = 100 * 1024 * 1024  # 100 MB
MAX_MEMORY_MB: Final[int] = 500                # Лимит RAM в мегабайтах
MAX_RUNTIME_SEC: Final[int] = 30               # Лимит времени обработки

class XMLEntityError(Exception):
    """Ошибка безопасности или превышения лимитов XML."""
    pass

class SecureXMLProcessor:
    """Сервис потоковой обработки XML с контролем ресурсов."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._start_time = 0

    def _check_resources(self):
        """Проверяет потребление памяти и оставшееся время."""
        # Проверка времени
        if (time.time() - self._start_time) > MAX_RUNTIME_SEC:
            raise XMLEntityError("Processing time limit exceeded.")

        # Проверка памяти текущего процесса
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info().rss / (1024 * 1024)
        if mem_info > MAX_MEMORY_MB:
            raise XMLEntityError(f"Memory limit exceeded: {mem_info:.2f}MB")

    def process_reports(self) -> Generator[dict, None, None]:
        """
        Потоковый парсинг XML (iterparse) с защитой от атак и перегрузок.
        """
        # 1. Проверка размера файла перед началом
        if os.path.getsize(self.file_path) > MAX_FILE_SIZE:
            raise XMLEntityError("File size exceeds allowed limit.")

        self._start_time = time.time()

        # 2. Настройка парсера с защитой от внешних сущностей (XXE/Billion Laughs)
        # resolve_entities=False отключает подстановку сущностей
        parser = etree.XMLParser(resolve_entities=False, dtd_validation=False)

        try:
            # Используем iterparse для чтения только нужных элементов (например, 'report')
            context = etree.iterparse(
                self.file_path, 
                events=('end',), 
                tag='report', 
                parser=parser
            )

            for event, elem in context:
                # Периодическая проверка ресурсов внутри цикла
                self._check_resources()

                # Обработка данных
                report_data = {
                    "id": elem.get("id"),
                    "value": elem.findtext("value")
                }
                
                yield report_data

                # КРИТИЧНО: Очистка обработанных элементов из памяти
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]

        except etree.XMLSyntaxError as e:
            raise XMLEntityError(f"Invalid XML syntax: {e}")
        finally:
            if 'context' in locals():
                del contextЫы