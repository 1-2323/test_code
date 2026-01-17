import threading
import requests
from typing import Callable, Any
from functools import wraps

# =========================
# CONFIGURATION
# =========================

LICENSE_SERVER_URL = "https://license.example.com/validate"
APPLICATION_ID = "my_app"
LICENSE_KEY = "REPLACE_WITH_LICENSE_KEY"

REQUEST_TIMEOUT = 5


# =========================
# LICENSE STATE
# =========================

class LicenseState:
    """
    Глобальное состояние лицензии приложения.
    """
    _lock = threading.Lock()
    _valid: bool | None = None
    _error: str | None = None

    @classmethod
    def set_valid(cls) -> None:
        with cls._lock:
            cls._valid = True
            cls._error = None

    @classmethod
    def set_invalid(cls, error: str) -> None:
        with cls._lock:
            cls._valid = False
            cls._error = error

    @classmethod
    def is_valid(cls) -> bool:
        with cls._lock:
            return cls._valid is True

    @classmethod
    def ensure_valid(cls) -> None:
        with cls._lock:
            if cls._valid is not True:
                raise RuntimeError(
                    f"License check failed: {cls._error or 'unknown error'}"
                )


# =========================
# LICENSE CHECKER
# =========================

class LicenseChecker:
    """
    Проверка лицензии при старте приложения.
    """

    @staticmethod
    def verify_on_startup() -> None:
        try:
            response = requests.post(
                LICENSE_SERVER_URL,
                json={
                    "application_id": APPLICATION_ID,
                    "license_key": LICENSE_KEY,
                },
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                LicenseState.set_invalid(
                    f"License server error: HTTP {response.status_code}"
                )
                return

            payload = response.json()

            if payload.get("status") != "valid":
                LicenseState.set_invalid("License rejected by server")
                return

            LicenseState.set_valid()

        except requests.RequestException:
            LicenseState.set_invalid("License server unreachable")


# =========================
# FUNCTION GUARD
# =========================

def license_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Декоратор, блокирующий выполнение функций при невалидной лицензии.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        LicenseState.ensure_valid()
        return func(*args, **kwargs)

    return wrapper


# =========================
# APPLICATION INIT
# =========================

def initialize_application() -> None:
    """
    Инициализация приложения с обязательной проверкой лицензии.
    """
    LicenseChecker.verify_on_startup()
    LicenseState.ensure_valid()


# =========================
# EXAMPLE PROTECTED API
# =========================

@license_required
def critical_business_function(data: str) -> str:
    return f"Processed: {data}"


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":
    initialize_application()

    # Любой вызов защищённой функции без валидной лицензии приведёт к исключению
    result = critical_business_function("important payload")
    print(result)
