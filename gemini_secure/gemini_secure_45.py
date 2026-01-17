import functools
import time
from typing import Optional, Final
import httpx
import jwt  # PyJWT

# --- Конфигурация безопасности ---
LICENSE_SERVER_URL: Final[str] = "https://api.licensing-service.com/v1/verify"
# Публичный ключ сервера для проверки подписи ответа (защита от спуфинга)
SERVER_PUBLIC_KEY: Final[str] = """-----BEGIN PUBLIC KEY-----
...Ключ сервера...
-----END PUBLIC KEY-----"""

class LicenseState:
    """Глобальное состояние лицензии в памяти приложения."""
    _is_verified: bool = False
    _last_check_time: float = 0
    _license_info: dict = {}

    @classmethod
    def set_verified(cls, info: dict):
        cls._is_verified = True
        cls._last_check_time = time.time()
        cls._license_info = info

    @classmethod
    def is_valid(cls) -> bool:
        # Проверка: лицензия подтверждена и проверка была недавно (например, < 1 часа назад)
        return cls._is_verified and (time.time() - cls._last_check_time < 3600)

# --- Декоратор блокировки функций ---

def require_license(func):
    """Декоратор, блокирующий выполнение функции без валидной лицензии."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not LicenseState.is_valid():
            print("Ошибка: Ключевая функция заблокирована. Лицензия не подтверждена.")
            # Вместо завершения процесса можно выбросить исключение, 
            # чтобы UI мог корректно обработать это состояние.
            raise PermissionError("Application license is invalid or expired.")
        return func(*args, **kwargs)
    return wrapper

# --- Сервис проверки ---

class LicenseManager:
    """Логика взаимодействия с сервером лицензий."""

    def __init__(self, license_key: str):
        self.license_key = license_key

    async def check_online(self) -> bool:
        """
        Выполняет запрос к серверу и проверяет криптографическую подпись ответа.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    LICENSE_SERVER_URL, 
                    json={"license_key": self.license_key}
                )
                
                if response.status_code != 200:
                    return False

                # Сервер должен вернуть JWT, подписанный своим приватным ключом
                token = response.json().get("token")
                
                # Декодируем и проверяем подпись
                payload = jwt.decode(
                    token, 
                    SERVER_PUBLIC_KEY, 
                    algorithms=["RS256"]
                )
                
                if payload.get("status") == "active":
                    LicenseState.set_verified(payload)
                    return True
                
        except (httpx.RequestError, jwt.PyJWTError) as e:
            # Любая ошибка сети или валидации трактуется как отказ
            print(f"License check failed: {e}")
            
        return False

