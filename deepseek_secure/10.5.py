import defusedxml.cElementTree as ET
from defusedxml.common import DefusedXmlException
import os
from typing import Optional, Callable, Dict, Any
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SafeXMLParser:
    """Безопасный парсер больших XML-файлов с защитой от XXE и Billion Laughs атак."""
    
    def __init__(
        self,
        max_file_size_mb: int = 100,
        max_element_depth: int = 20,
        max_element_count: int = 1000000,
        max_entity_expansions: int = 100,
        forbid_dtd: bool = True,
        forbid_entities: bool = True,
        forbid_external: bool = True
    ):
        """
        Инициализация парсера с настройками безопасности.
        
        Args:
            max_file_size_mb: Максимальный размер файла в МБ
            max_element_depth: Максимальная глубина вложенности элементов
            max_element_count: Максимальное количество элементов
            max_entity_expansions: Максимальное количество расширений сущностей
            forbid_dtd: Запретить DTD
            forbid_entities: Запретить сущности
            forbid_external: Запретить внешние ресурсы
        """
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.max_element_depth = max_element_depth
        self.max_element_count = max_element_count
        self.max_entity_expansions = max_entity_expansions
        self.forbid_dtd = forbid_dtd
        self.forbid_entities = forbid_entities
        self.forbid_external = forbid_external
        
        # Настройка парсера defusedxml
        self._configure_defusedxml()
    
    def _configure_defusedxml(self) -> None:
        """Конфигурация параметров безопасности defusedxml."""
        # Ограничение на глубину элементов
        if hasattr(ET, 'XMLParser'):
            parser = ET.XMLParser()
            if hasattr(parser, '_parser'):
                parser._parser.SetSecurityLimits(
                    max_depth=self.max_element_depth,
                    max_children=self.max_element_count,
                    max_entity_expansions=self.max_entity_expansions
                )
    
    def _validate_file_size(self, file_path: str) -> bool:
        """Проверка размера файла перед обработкой."""
        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size_bytes:
                logger.error(f"Файл слишком большой: {file_size} байт (максимум: {self.max_file_size_bytes})")
                return False
            return True
        except OSError as e:
            logger.error(f"Ошибка проверки размера файла: {e}")
            return False
    
    def parse_xml_file(
        self,
        file_path: str,
        element_handler: Optional[Callable[[ET.Element, Dict[str, Any]], None]] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> Optional[ET.ElementTree]:
        """
        Безопасный парсинг XML-файла.
        
        Args:
            file_path: Путь к XML-файлу
            element_handler: Функция-обработчик для каждого элемента (опционально)
            context_data: Дополнительные данные для обработчика
            
        Returns:
            ElementTree или None в случае ошибки
        """
        if not self._validate_file_size(file_path):
            return None
        
        if context_data is None:
            context_data = {}
        
        try:
            logger.info(f"Начало обработки файла: {file_path}")
            
            # Используем iterparse для потоковой обработки больших файлов
            context = ET.iterparse(
                file_path,
                events=('start', 'end'),
                forbid_dtd=self.forbid_dtd,
                forbid_entities=self.forbid_entities,
                forbid_external=self.forbid_external
            )
            
            element_stack = []
            element_count = 0
            
            for event, elem in context:
                if event == 'start':
                    element_stack.append(elem)
                    element_count += 1
                    
                    # Проверка количества элементов
                    if element_count > self.max_element_count:
                        logger.error(f"Превышено максимальное количество элементов: {self.max_element_count}")
                        return None
                    
                    # Проверка глубины вложенности
                    if len(element_stack) > self.max_element_depth:
                        logger.error(f"Превышена максимальная глубина элементов: {self.max_element_depth}")
                        return None
                
                elif event == 'end':
                    # Вызов обработчика элемента, если он предоставлен
                    if element_handler:
                        try:
                            element_handler(elem, context_data)
                        except Exception as e:
                            logger.warning(f"Ошибка в обработчике элемента {elem.tag}: {e}")
                    
                    # Очистка обработанных элементов для экономии памяти
                    if element_stack:
                        parent = element_stack.pop()
                        if parent is not elem:
                            logger.warning("Несоответствие стека элементов")
                    
                    # Очищаем элемент после обработки
                    elem.clear()
            
            logger.info(f"Обработка завершена. Обработано элементов: {element_count}")
            
            # Возвращаем корневой элемент
            return ET.parse(
                file_path,
                forbid_dtd=self.forbid_dtd,
                forbid_entities=self.forbid_entities,
                forbid_external=self.forbid_external
            )
            
        except DefusedXmlException as e:
            logger.error(f"Обнаружена XML-атака или нарушение безопасности: {e}")
            return None
        except ET.ParseError as e:
            logger.error(f"Ошибка парсинга XML: {e}")
            return None
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при обработке файла: {e}")
            return None
    
    def extract_data_with_xpath(
        self,
        file_path: str,
        xpath_query: str,
        namespaces: Optional[Dict[str, str]] = None
    ) -> Optional[list]:
        """
        Извлечение данных с помощью XPath с ограничениями безопасности.
        
        Args:
            file_path: Путь к XML-файлу
            xpath_query: XPath выражение
            namespaces: Пространства имен для XPath
            
        Returns:
            Список найденных элементов или None в случае ошибки
        """
        try:
            tree = self.parse_xml_file(file_path)
            if tree is None:
                return None
            
            root = tree.getroot()
            
            # Применяем XPath с ограничением количества результатов
            results = root.findall(xpath_query, namespaces=namespaces or {})
            
            # Дополнительная проверка на количество результатов
            if len(results) > self.max_element_count:
                logger.warning(f"Найдено слишком много результатов XPath: {len(results)}")
                results = results[:self.max_element_count]
            
            return results
            
        except Exception as e:
            logger.error(f"Ошибка при выполнении XPath запроса: {e}")
            return None

# Пример использования функции (без имплементации):
def create_safe_xml_parser() -> SafeXMLParser:
    """Создание экземпляра безопасного парсера с настройками по умолчанию."""
    return SafeXMLParser(
        max_file_size_mb=50,
        max_element_depth=15,
        max_element_count=500000,
        max_entity_expansions=50,
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True
    )