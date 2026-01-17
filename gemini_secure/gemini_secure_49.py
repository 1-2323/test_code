import lxml.etree as etree
import logging
from typing import Optional

# Настройка безопасного логгера
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("SafeXMLParser")

class XMLParserError(Exception):
    """Кастомное исключение с нейтральным сообщением."""
    pass

class SafeXMLParser:
    """Парсер XML с защитой от XXE и утечки данных в ошибках."""

    def __init__(self):
        # 1. Настройка безопасного парсера:
        # resolve_entities=False — запрещает раскрытие сущностей
        # no_network=True — запрещает доступ к сетевым ресурсам при парсинге
        # dtd_validation=False — отключает валидацию DTD
        self.parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            dtd_validation=False,
            remove_comments=True
        )

    def parse(self, xml_string: bytes) -> Optional[etree._Element]:
        """Парсит XML и возвращает корневой элемент или вызывает исключение."""
        try:
            # Преобразуем входные данные в байты, если это строка
            if isinstance(xml_string, str):
                xml_string = xml_string.encode('utf-8')

            root = etree.fromstring(xml_string, parser=self.parser)
            return root

        except etree.XMLSyntaxError as e:
            # 2. Перехват детальной ошибки и ее нейтрализация.
            # Мы логируем полную ошибку внутри системы для разработчиков,
            # но пользователю возвращаем только безопасное сообщение.
            logger.error(f"Internal XML Syntax Error: {str(e)}")
            
            # Мы не передаем объект 'e' или его атрибуты вовне, 
            # чтобы избежать вывода фрагментов кода или путей.
            raise XMLParserError("Invalid XML format. Please check the document structure.") from None

        except Exception as e:
            logger.error(f"Unexpected parser error: {str(e)}")
            raise XMLParserError("An error occurred while processing the XML document.") from None