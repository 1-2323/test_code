import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import logging
import re
from xml.sax import make_parser, handler
import defusedxml.ElementTree as DET
import defusedxml.minidom
import defusedxml.sax

# Настройка логирования
logging.basicConfig(level=logging.WARNING)  # Уменьшаем уровень для безопасности
logger = logging.getLogger(__name__)


class SafeXMLParserError(Exception):
    """Базовое исключение безопасного парсера XML"""
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        # Безопасное форматирование сообщения об ошибке
        safe_message = self._sanitize_error_message(message)
        super().__init__(safe_message)
        self.original_error = original_error
    
    @staticmethod
    def _sanitize_error_message(message: str) -> str:
        """
        Очистка сообщения об ошибке от чувствительной информации
        
        Args:
            message: исходное сообщение об ошибке
            
        Returns:
            Очищенное безопасное сообщение
        """
        # Удаляем пути к файлам
        message = re.sub(r'(/[^/\s]+)+', '[FILE_PATH]', message)
        
        # Удаляем содержимое внешних сущностей
        message = re.sub(r'&[^;]+;', '[ENTITY]', message)
        
        # Удаляем возможные системные пути
        message = re.sub(r'[A-Za-z]:\\[^\\\s]+', '[SYSTEM_PATH]', message)
        
        # Удаляем IP-адреса
        message = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '[IP_ADDRESS]', message)
        
        # Удаляем слишком длинные строки (возможный бинарный контент)
        message = re.sub(r'.{100,}', '[LONG_CONTENT]', message)
        
        return message


class XXEError(SafeXMLParserError):
    """Исключение при обнаружении XXE атаки"""
    pass


class XMLSyntaxError(SafeXMLParserError):
    """Исключение при синтаксической ошибке XML"""
    pass


@dataclass
class ParsedElement:
    """Безопасно распарсенный XML элемент"""
    tag: str
    text: Optional[str]
    attributes: Dict[str, str]
    children: List['ParsedElement']


class SafeXMLParser:
    """
    Безопасный парсер XML документов с защитой от XXE и других атак.
    Не выводит содержимое внешних сущностей в сообщениях об ошибках.
    """
    
    def __init__(self, 
                 forbid_dtd: bool = True,
                 forbid_entities: bool = True,
                 forbid_external: bool = True,
                 max_depth: int = 50,
                 max_elements: int = 100000):
        """
        Инициализация безопасного парсера XML
        
        Args:
            forbid_dtd: запретить DTD
            forbid_entities: запретить внешние сущности
            forbid_external: запретить внешние ресурсы
            max_depth: максимальная глубина вложенности
            max_elements: максимальное количество элементов
        """
        self.forbid_dtd = forbid_dtd
        self.forbid_entities = forbid_entities
        self.forbid_external = forbid_external
        self.max_depth = max_depth
        self.max_elements = max_elements
        self._element_count = 0
        
    def parse_file(self, file_path: str) -> ParsedElement:
        """
        Безопасный парсинг XML файла
        
        Args:
            file_path: путь к XML файлу
            
        Returns:
            Корневой элемент распарсенного документа
            
        Raises:
            XXEError: при обнаружении XXE атаки
            XMLSyntaxError: при синтаксической ошибке
            SafeXMLParserError: при других ошибках парсинга
        """
        try:
            # Используем defusedxml для защиты от XXE
            if self.forbid_dtd:
                # Полностью отключаем DTD
                parser = DET.DefusedXMLParser(
                    forbid_dtd=True,
                    forbid_entities=self.forbid_entities,
                    forbid_external=self.forbid_external
                )
            else:
                parser = DET.DefusedXMLParser(
                    forbid_entities=self.forbid_entities,
                    forbid_external=self.forbid_external
                )
            
            # Парсим файл
            tree = DET.parse(file_path, parser=parser)
            root = tree.getroot()
            
            # Безопасно обрабатываем дерево элементов
            return self._safe_parse_element(root, depth=0)
            
        except DET.EntitiesForbidden as e:
            raise XXEError("Обнаружены запрещенные внешние сущности", e)
            
        except DET.ExternalReferenceForbidden as e:
            raise XXEError("Обнаружены запрещенные внешние ссылки", e)
            
        except ET.ParseError as e:
            # Безопасно обрабатываем ошибки парсинга
            safe_msg = self._get_safe_parse_error(str(e))
            raise XMLSyntaxError(f"Синтаксическая ошибка XML: {safe_msg}", e)
            
        except Exception as e:
            # Общая обработка ошибок с санитизацией сообщения
            raise SafeXMLParserError(f"Ошибка парсинга XML: {str(e)}", e)
    
    def parse_string(self, xml_string: str) -> ParsedElement:
        """
        Безопасный парсинг XML строки
        
        Args:
            xml_string: строка с XML
            
        Returns:
            Корневой элемент распарсенного документа
            
        Raises:
            XXEError: при обнаружении XXE атаки
            XMLSyntaxError: при синтаксической ошибке
            SafeXMLParserError: при других ошибках парсинга
        """
        try:
            # Проверяем строку на наличие опасных конструкций
            self._validate_xml_string(xml_string)
            
            # Используем defusedxml для защиты от XXE
            if self.forbid_dtd:
                parser = DET.DefusedXMLParser(
                    forbid_dtd=True,
                    forbid_entities=self.forbid_entities,
                    forbid_external=self.forbid_external
                )
            else:
                parser = DET.DefusedXMLParser(
                    forbid_entities=self.forbid_entities,
                    forbid_external=self.forbid_external
                )
            
            # Парсим строку
            root = DET.fromstring(xml_string, parser=parser)
            
            # Безопасно обрабатываем дерево элементов
            return self._safe_parse_element(root, depth=0)
            
        except DET.EntitiesForbidden as e:
            raise XXEError("Обнаружены запрещенные внешние сущности", e)
            
        except DET.ExternalReferenceForbidden as e:
            raise XXEError("Обнаружены запрещенные внешние ссылки", e)
            
        except ET.ParseError as e:
            # Безопасно обрабатываем ошибки парсинга
            safe_msg = self._get_safe_parse_error(str(e))
            raise XMLSyntaxError(f"Синтаксическая ошибка XML: {safe_msg}", e)
            
        except Exception as e:
            # Общая обработка ошибок с санитизацией сообщения
            raise SafeXMLParserError(f"Ошибка парсинга XML: {str(e)}", e)
    
    def _safe_parse_element(self, element: ET.Element, depth: int) -> ParsedElement:
        """
        Безопасный парсинг элемента XML с контролем ресурсов
        
        Args:
            element: элемент XML
            depth: текущая глубина вложенности
            
        Returns:
            Безопасно распарсенный элемент
            
        Raises:
            SafeXMLParserError: при превышении лимитов
        """
        # Проверка глубины вложенности
        if depth > self.max_depth:
            raise SafeXMLParserError(
                f"Превышена максимальная глубина вложенности ({self.max_depth})"
            )
        
        # Проверка количества элементов
        self._element_count += 1
        if self._element_count > self.max_elements:
            raise SafeXMLParserError(
                f"Превышено максимальное количество элементов ({self.max_elements})"
            )
        
        # Безопасное извлечение текста
        safe_text = None
        if element.text:
            # Ограничиваем длину текста и удаляем опасные символы
            safe_text = self._sanitize_text(element.text)
        
        # Безопасное извлечение атрибутов
        safe_attributes = {}
        for key, value in element.attrib.items():
            safe_attributes[key] = self._sanitize_text(value)
        
        # Рекурсивная обработка дочерних элементов
        safe_children = []
        for child in element:
            try:
                parsed_child = self._safe_parse_element(child, depth + 1)
                safe_children.append(parsed_child)
            except SafeXMLParserError:
                # Пропускаем проблемные дочерние элементы
                logger.warning(f"Пропущен дочерний элемент {child.tag}")
                continue
        
        return ParsedElement(
            tag=element.tag,
            text=safe_text,
            attributes=safe_attributes,
            children=safe_children
        )
    
    def _sanitize_text(self, text: str) -> str:
        """
        Очистка текста от потенциально опасного содержимого
        
        Args:
            text: исходный текст
            
        Returns:
            Очищенный текст
        """
        if not text:
            return text
        
        # Удаляем нулевые байты
        text = text.replace('\x00', '')
        
        # Удаляем управляющие символы (кроме табуляции и перевода строки)
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        
        # Ограничиваем длину
        if len(text) > 10000:
            text = text[:10000] + "... [TRIMMED]"
        
        return text
    
    def _validate_xml_string(self, xml_string: str) -> None:
        """
        Проверка XML строки на наличие опасных конструкций
        
        Args:
            xml_string: строка XML для проверки
            
        Raises:
            XXEError: при обнаружении опасных конструкций
        """
        # Проверка на DOCTYPE (потенциальный XXE)
        if re.search(r'<!DOCTYPE', xml_string, re.IGNORECASE):
            raise XXEError("Обнаружен DOCTYPE - потенциальная XXE атака")
        
        # Проверка на внешние сущности
        if re.search(r'&[^;]+;', xml_string):
            # Проверяем, не являются ли сущности внешними
            if re.search(r'&(file|http|ftp|php):', xml_string, re.IGNORECASE):
                raise XXEError("Обнаружены потенциально опасные внешние сущности")
        
        # Проверка на слишком большие документы
        if len(xml_string) > 10 * 1024 * 1024:  # 10 MB
            raise SafeXMLParserError("XML документ слишком большой")
    
    def _get_safe_parse_error(self, error_message: str) -> str:
        """
        Получение безопасного сообщения об ошибке парсинга
        
        Args:
            error_message: исходное сообщение об ошибке
            
        Returns:
            Безопасное сообщение об ошибке
        """
        # Санитизируем сообщение об ошибке
        safe_message = SafeXMLParserError._sanitize_error_message(error_message)
        
        # Упрощаем сообщение для пользователя
        patterns = [
            (r'syntax error', 'Синтаксическая ошибка в XML документе'),
            (r'not well-formed', 'Некорректный формат XML документа'),
            (r'unclosed token', 'Незакрытый тег в XML документе'),
            (r'mismatched tag', 'Несоответствие открывающих и закрывающих тегов'),
        ]
        
        for pattern, replacement in patterns:
            if re.search(pattern, safe_message, re.IGNORECASE):
                return replacement
        
        return "Ошибка парсинга XML документа"
    
    def get_xml_summary(self, root: ParsedElement) -> Dict[str, Any]:
        """
        Получение безопасной сводки по XML документу
        
        Args:
            root: корневой элемент
            
        Returns:
            Словарь со сводкой документа
        """
        def count_elements(element: ParsedElement) -> int:
            count = 1
            for child in element.children:
                count += count_elements(child)
            return count
        
        def get_unique_tags(element: ParsedElement, tags: set) -> set:
            tags.add(element.tag)
            for child in element.children:
                tags = get_unique_tags(child, tags)
            return tags
        
        total_elements = count_elements(root)
        unique_tags = get_unique_tags(root, set())
        
        return {
            "root_tag": root.tag,
            "total_elements": total_elements,
            "unique_tags": list(unique_tags),
            "has_attributes": bool(root.attributes),
            "has_text": root.text is not None and len(root.text) > 0
        }


# Пример использования
def main():
    """Пример использования безопасного парсера XML"""
    
    # Инициализация безопасного парсера
    parser = SafeXMLParser(
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
        max_depth=100,
        max_elements=1000000
    )
    
    # Пример безопасного XML
    safe_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <catalog>
        <book id="1">
            <title>Clean Code</title>
            <author>Robert Martin</author>
            <price>45.99</price>
        </book>
        <book id="2">
            <title>Design Patterns</title>
            <author>Gang of Four</author>
            <price>55.50</price>
        </book>
    </catalog>"""
    
    try:
        # Безопасный парсинг строки
        result = parser.parse_string(safe_xml)
        
        # Получение безопасной сводки
        summary = parser.get_xml_summary(result)
        
        print("XML успешно распарсен")
        print(f"Корневой тег: {summary['root_tag']}")
        print(f"Всего элементов: {summary['total_elements']}")
        print(f"Уникальные теги: {summary['unique_tags']}")
        
        # Пример опасного XML (будет отклонен)
        dangerous_xml = """<?xml version="1.0"?>
        <!DOCTYPE foo [
        <!ELEMENT foo ANY >
        <!ENTITY xxe SYSTEM "file:///etc/passwd" >]>
        <foo>&xxe;</foo>"""
        
        print("\nПопытка парсинга опасного XML...")
        try:
            parser.parse_string(dangerous_xml)
        except XXEError as e:
            print(f"Обнаружена и предотвращена XXE атака: {e}")
        except SafeXMLParserError as e:
            print(f"Безопасно обработанная ошибка: {e}")
            
    except SafeXMLParserError as e:
        print(f"Безопасная ошибка парсинга: {e}")
        # В сообщении об ошибке НЕ будет содержимого файлов или системных путей


if __name__ == "__main__":
    main()