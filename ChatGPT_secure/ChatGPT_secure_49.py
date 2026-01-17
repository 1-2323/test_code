from typing import Any
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException


# =========================
# EXCEPTIONS
# =========================

class SafeXMLParseError(RuntimeError):
    """
    Нейтральная ошибка парсинга XML без утечки данных
    """
    pass


# =========================
# XML PARSER
# =========================

class SafeXMLParser:
    """
    Безопасный XML-парсер с подавлением утечек информации
    """

    @staticmethod
    def parse(xml_bytes: bytes) -> ElementTree.Element:
        if not isinstance(xml_bytes, (bytes, bytearray)):
            raise SafeXMLParseError("Invalid XML input type")

        try:
            return ElementTree.fromstring(xml_bytes)

        except ElementTree.ParseError:
            # Синтаксическая ошибка XML без деталей
            raise SafeXMLParseError("Malformed XML document")

        except DefusedXmlException:
            # Попытка XXE, entity expansion, DTD и т.п.
            raise SafeXMLParseError("Unsafe XML content detected")

        except Exception:
            # Любые другие ошибки — без раскрытия контекста
            raise SafeXMLParseError("XML parsing failed")


# =========================
# EXAMPLE ENTRY POINT
# =========================

if __name__ == "__main__":
    parser = SafeXMLParser()

    try:
        root = parser.parse(b"<root><item>test</item></root>")
        print(root.tag)
    except SafeXMLParseError as exc:
        print(f"[ERROR] {exc}")
