import lxml.etree as ET
import logging
from typing import Optional

# Настройка логирования для аудита безопасности
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SecureXMLParser")

class SecureXMLParser:
    """
    Парсер XML, защищенный от XXE-атак и раскрытия системной информации.
    """

    def __init__(self):
        # Создаем конфигурацию парсера с отключенным разрешением внешних сущностей
        self.parser_config = ET.XMLParser(
            resolve_entities=False,     # Запрет на разрешение сущностей
            no_network=True,            # Запрет сетевых запросов при парсинге
            dtd_validation=False,       # Отключение валидации DTD
            load_dtd=False,             # Запрет загрузки внешних DTD
            remove_comments=True        # Очистка комментариев для безопасности
        )

    def parse_safely(self, xml_input: str) -> Optional[ET._Element]:
        """
        Парсит XML-строку и безопасно обрабатывает ошибки.
        """
        try:
            # Преобразуем строку в байты, если это необходимо
            xml_bytes = xml_input.encode('utf-8') if isinstance(xml_input, str) else xml_input
            
            root = ET.fromstring(xml_bytes, parser=self.parser_config)
            return root

        except ET.XMLSyntaxError as e:
            # КРИТИЧНО: Мы перехватываем ошибку синтаксиса и логируем её,
            # но пользователю возвращаем только общее сообщение без деталей контекста.
            
            # Логируем полную ошибку для администратора (в защищенное хранилище)
            logger.error(f"Syntax error detected during XML parsing: {str(e)}")
            
            # Выбрасываем исключение с очищенным текстом
            # Мы не передаем объект 'e' дальше, чтобы не раскрыть куски кода или путей
            raise ValueError("Ошибка обработки XML: Некорректный синтаксис или недопустимые структуры данных.")

        except Exception as e:
            logger.critical(f"Unexpected error during XML processing: {str(e)}")
            raise ValueError("Произошла системная ошибка при обработке документа.")

# --- Демонстрация работы ---

if __name__ == "__main__":
    secure_parser = SecureXMLParser()

    # Пример 1: Обычный корректный XML
    valid_xml = "<user><name>Alex</name></user>"
    result = secure_parser.parse_safely(valid_xml)
    if result is not None:
        print(f"Успешно распарсено: {result.tag}")

    # Пример 2: Попытка XXE-атаки (чтение системного файла)
    malicious_xml = """<?xml version="1.0" encoding="ISO-8859-1"?>
    <!DOCTYPE foo [  
      <!ELEMENT foo ANY >
      <!ENTITY xxe SYSTEM "file:///etc/passwd" >]>
    <foo>&xxe;</foo>"""

    print("\nПопытка парсинга вредоносного XML...")
    try:
        secure_parser.parse_safely(malicious_xml)
    except ValueError as e:
        print(f"Безопасно перехвачено: {e}")

    # Пример 3: XML с синтаксической ошибкой
    broken_xml = "<root><unclosed_tag>"
    print("\nПопытка парсинга битого XML...")
    try:
        secure_parser.parse_safely(broken_xml)
    except ValueError as e:
        print(f"Безопасно перехвачено: {e}")