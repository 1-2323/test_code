import io
import time
import signal
import resource
from dataclasses import dataclass
from typing import Iterable, Optional

from defusedxml.ElementTree import iterparse, ParseError


# =========================
# LIMITS & CONFIG
# =========================

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_PROCESSING_SECONDS = 5               # wall-clock time limit
MAX_MEMORY_MB = 256                      # address space limit (Unix)
ALLOWED_ROOT_TAGS = {"report", "dataset"}


# =========================
# EXCEPTIONS
# =========================

class XMLProcessingError(RuntimeError):
    pass


class LimitExceededError(XMLProcessingError):
    pass


# =========================
# LIMIT ENFORCEMENT
# =========================

def _set_memory_limit(max_mb: int) -> None:
    max_bytes = max_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))


def _timeout_handler(signum, frame) -> None:  # type: ignore[override]
    raise LimitExceededError("Processing time limit exceeded")


# =========================
# DATA MODEL
# =========================

@dataclass(frozen=True)
class ParsedItem:
    tag: str
    attributes: dict[str, str]
    text: Optional[str]


# =========================
# XML PROCESSOR
# =========================

class HeavyXMLProcessor:
    """
    Потоковый и безопасный обработчик XML-отчетов с жесткими лимитами
    по размеру, времени и памяти.
    """

    def __init__(self) -> None:
        self._start_time: float = 0.0

    def process(self, raw_bytes: bytes) -> list[ParsedItem]:
        self._validate_size(raw_bytes)
        self._apply_limits()

        self._start_time = time.monotonic()
        results: list[ParsedItem] = []

        try:
            with io.BytesIO(raw_bytes) as stream:
                context = iterparse(stream, events=("start", "end"))

                root_checked = False

                for event, elem in context:
                    self._check_time()

                    if event == "start" and not root_checked:
                        if elem.tag not in ALLOWED_ROOT_TAGS:
                            raise XMLProcessingError("Unsupported root element")
                        root_checked = True

                    if event == "end":
                        results.append(
                            ParsedItem(
                                tag=elem.tag,
                                attributes=dict(elem.attrib),
                                text=(elem.text or "").strip() or None,
                            )
                        )
                        elem.clear()

        except LimitExceededError:
            raise
        except ParseError as exc:
            raise XMLProcessingError(f"Invalid XML: {exc}") from exc
        finally:
            signal.alarm(0)

        return results

    # =========================
    # INTERNALS
    # =========================

    @staticmethod
    def _validate_size(data: bytes) -> None:
        if len(data) > MAX_FILE_SIZE_BYTES:
            raise LimitExceededError("XML file exceeds maximum allowed size")

    @staticmethod
    def _apply_limits() -> None:
        _set_memory_limit(MAX_MEMORY_MB)
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_PROCESSING_SECONDS)

    def _check_time(self) -> None:
        if time.monotonic() - self._start_time > MAX_PROCESSING_SECONDS:
            raise LimitExceededError("Processing time limit exceeded")


# =========================
# ENTRY POINT (EXAMPLE USAGE)
# =========================

if __name__ == "__main__":
    processor = HeavyXMLProcessor()

    with open("input.xml", "rb") as f:
        xml_bytes = f.read()

    try:
        items = processor.process(xml_bytes)
        print(f"Processed {len(items)} XML elements safely")
    except XMLProcessingError as exc:
        print(f"[ERROR] {exc}")
