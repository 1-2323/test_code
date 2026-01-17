import hashlib
import uuid
import httpx
from functools import wraps
from typing import Callable, Optional

class LicenseError(Exception):
    """Исключение, выбрасываемое при отсутствии валидной лицензии."""
    pass

class LicenseManager:
    """
    Сервис проверки лицензии с привязкой к оборудованию.
    """
    def __init__(self, server_url: str, license_key: str):
        self.server_url = server_url
        self.license_key = license_key
        self._is_verified = False
        self._hwid = self._get_hwid()

    def _get_hwid(self) -> str:
        """Генерирует уникальный ID текущего устройства (на основе MAC-адреса)."""
        node = uuid.getnode()
        return hashlib.sha256(str(node).encode()).hexdigest()

    def check_license(self) -> bool:
        """
        Выполняет запрос к удаленному серверу для проверки лицензии.
        """
        try:
            # В реальной системе стоит использовать HMAC или подпись для защиты ответа
            payload = {
                "license_key": self.license_key,
                "hwid": self._hwid
            }
            
            with httpx.Client(timeout=10.0) as client:
                response = client.post(f"{self.server_url}/verify", json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    self._is_verified = data.get("status") == "active"
                else:
                    self._is_verified = False
                    
        except (httpx.RequestError, Exception):
            # Если сервер недоступен, блокируем запуск (Fail-Safe: Off)
            self._is_verified = False
            
        return self._is_verified

    @property
    def is_active(self) -> bool:
        return self._is_verified

# --- Декоратор для защиты функций ---

def require_license(manager: LicenseManager):
    """
    Декоратор, который блокирует выполнение функции при невалидной лицензии.
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not manager.is_active:
                raise LicenseError(
                    f"Функция '{func.__name__}' заблокирована. "
                    "Лицензия не активна или сервер недоступен."
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator

# --- Пример интеграции ---

# 1. Инициализация (обычно при старте приложения)
license_mgr = LicenseManager(
    server_url="https://api.myapp.com/v1", 
    license_key="ABCD-1234-EFGH-5678"
)

# Проверка при запуске
print("[*] Проверка лицензии...")
license_mgr.check_license()

# 2. Защищенные функции
@require_license(license_mgr)
def export_data_to_excel(data: list):
    print("Экспорт данных успешно выполнен.")

@require_license(license_mgr)
def run_heavy_computation():
    print("Сложные вычисления завершены.")

# --- Тест ---
try:
    if license_mgr.is_active:
        export_data_to_excel([1, 2, 3])
    else:
        print("Внимание: Программа работает в ограниченном режиме.")
        run_heavy_computation() # Это вызовет исключение
except LicenseError as e:
    print(f"Ошибка безопасности: {e}")