from dataclasses import dataclass
from typing import Optional, Union
from pathlib import Path

try:
    from defusedxml import lxml as defused_lxml  # type: ignore
    _HAS_DEFUSED = True
except Exception:
    _HAS_DEFUSED = False

from lxml import etree


class XMLParseError(Exception):
    """Raised when XML parsing or validation fails (sanitized message)."""


@dataclass(frozen=True)
class ParseResult:
    tree: etree._ElementTree
    root: etree._Element


class SafeXMLParser:
    def __init__(self, max_size_bytes: int = 10 * 1024 * 1024) -> None:
        self._max_size = max_size_bytes

    def parse_file(self, file_path: Union[str, Path]) -> ParseResult:
        path = Path(file_path)
        if not path.is_file():
            raise XMLParseError("XML error: file not found")

        try:
            size = path.stat().st_size
        except OSError:
            raise XMLParseError("XML error: cannot access file")

        if size > self._max_size:
            raise XMLParseError("XML error: file size exceeds allowed limit")

        try:
            if _HAS_DEFUSED:
                tree = defused_lxml.parse(str(path))
            else:
                parser = self._secure_parser()
                tree = etree.parse(str(path), parser=parser)
            root = tree.getroot()
            return ParseResult(tree=tree, root=root)
        except etree.XMLSyntaxError as exc:
            lineno = getattr(exc, "lineno", None)
            column = getattr(exc, "offset", None)
            msg = "XML syntax error"
            if lineno is not None:
                msg += f" at line {lineno}"
                if column is not None:
                    msg += f", column {column}"
            raise XMLParseError(msg)
        except Exception:
            raise XMLParseError("XML parsing failed")

    def parse_string(self, data: Union[str, bytes]) -> ParseResult:
        if isinstance(data, str):
            raw = data.encode("utf-8")
        else:
            raw = data

        if len(raw) > self._max_size:
            raise XMLParseError("XML error: payload size exceeds allowed limit")

        try:
            if _HAS_DEFUSED:
                root = defused_lxml.fromstring(raw)
                tree = etree.ElementTree(root)
            else:
                parser = self._secure_parser()
                root = etree.fromstring(raw, parser=parser)
                tree = etree.ElementTree(root)
            return ParseResult(tree=tree, root=root)
        except etree.XMLSyntaxError as exc:
            lineno = getattr(exc, "lineno", None)
            column = getattr(exc, "offset", None)
            msg = "XML syntax error"
            if lineno is not None:
                msg += f" at line {lineno}"
                if column is not None:
                    msg += f", column {column}"
            raise XMLParseError(msg)
        except Exception:
            raise XMLParseError("XML parsing failed")

    def _secure_parser(self) -> etree.XMLParser:
        return etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            recover=False,
            huge_tree=False,
        )


if __name__ == "__main__":
    parser = SafeXMLParser()

    # Example usage: parse file
    try:
        result = parser.parse_file("example.xml")
        print("Root tag:", result.root.tag)
    except XMLParseError as e:
        print("Parse failed:", str(e))

    # Example usage: parse string
    xml = "<root><child>value</child></root>"
    try:
        result = parser.parse_string(xml)
        print("Root tag:", result.root.tag)
    except XMLParseError as e:
        print("Parse failed:", str(e))
