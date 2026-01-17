import os
import signal
import sys
from dataclasses import dataclass
from typing import Any

from lxml import etree
import resource


MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_PROCESSING_SECONDS = 5
MAX_MEMORY_BYTES = 256 * 1024 * 1024


class XMLProcessingError(Exception):
    pass


@dataclass(frozen=True)
class XMLReportResult:
    root_tag: str
    elements_count: int


class ResourceLimiter:
    @staticmethod
    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
        signal.signal(signal.SIGALRM, ResourceLimiter._timeout)
        signal.alarm(MAX_PROCESSING_SECONDS)

    @staticmethod
    def reset() -> None:
        signal.alarm(0)

    @staticmethod
    def _timeout(signum: int, frame: Any) -> None:
        raise XMLProcessingError("Processing time limit exceeded")


class XMLReportProcessor:
    def process(self, file_path: str) -> XMLReportResult:
        self._validate_file(file_path)
        ResourceLimiter.apply()
        try:
            return self._parse(file_path)
        finally:
            ResourceLimiter.reset()

    def _validate_file(self, file_path: str) -> None:
        if not os.path.isfile(file_path):
            raise XMLProcessingError("File does not exist")
        if os.path.getsize(file_path) > MAX_FILE_SIZE_BYTES:
            raise XMLProcessingError("File size limit exceeded")

    def _parse(self, file_path: str) -> XMLReportResult:
        try:
            parser = etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                huge_tree=False,
            )
            tree = etree.parse(file_path, parser)
            root = tree.getroot()
            count = sum(1 for _ in root.iter())
            return XMLReportResult(
                root_tag=root.tag,
                elements_count=count,
            )
        except Exception as exc:
            raise XMLProcessingError(f"XML parsing failed: {exc}") from exc


def terminate(reason: str) -> None:
    print(f"XML REPORT REJECTED: {reason}")
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        terminate("XML file path required")

    processor = XMLReportProcessor()

    try:
        result = processor.process(sys.argv[1])
    except XMLProcessingError as exc:
        terminate(str(exc))

    print("XML processed successfully")
    print(result)


if __name__ == "__main__":
    main()
