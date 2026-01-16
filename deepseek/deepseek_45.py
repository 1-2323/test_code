import requests
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LicenseStatus(Enum):
    """Статусы лицензии"""
    VALID = "valid"
    INVALID = "invalid"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"


@dataclass
class LicenseCheckResult:
    """Результат проверки лицензии"""
    status: LicenseStatus
    message: str
    data: Optional[Dict[str, Any]] = None


class LicenseManager:
    """Менеджер лицензий с проверкой через удаленный сервер"""
    
    def __init__(self, license_server_url: str, license_key: str, timeout: int = 10):
        """
        Инициализация менеджера лицензий
        
        Args:
            license_server_url: URL сервера лицензий
            license_key: ключ лицензии
            timeout: таймаут запроса в секундах
        """
        self.license_server_url = license_server_url
        self.license_key = license_key
        self.timeout = timeout
        self._license_valid = False
        self._last_check_result: Optional[LicenseCheckResult] = None
        
    def check_license(self) -> LicenseCheckResult:
        """
        Проверка лицензии на удаленном сервере
        
        Returns:
            Результат проверки лицензии
        """
        try:
            response = requests.post(
                f"{self.license_server_url}/api/validate",
                json={"license_key": self.license_key},
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("valid", False):
                    result = LicenseCheckResult(
                        status=LicenseStatus.VALID,
                        message="Лицензия действительна",
                        data=data
                    )
                    self._license_valid = True
                else:
                    result = LicenseCheckResult(
                        status=LicenseStatus.INVALID,
                        message="Лицензия недействительна",
                        data=data
                    )
                    self._license_valid = False
            else:
                result = LicenseCheckResult(
                    status=LicenseStatus.SERVER_ERROR,
                    message=f"Ошибка сервера: {response.status_code}"
                )
                self._license_valid = False
                
        except requests.exceptions.Timeout:
            logger.error("Таймаут при проверке лицензии")
            result = LicenseCheckResult(
                status=LicenseStatus.NETWORK_ERROR,
                message="Сервер лицензий недоступен (таймаут)"
            )
            self._license_valid = False
            
        except requests.exceptions.ConnectionError:
            logger.error("Ошибка соединения с сервером лицензий")
            result = LicenseCheckResult(
                status=LicenseStatus.NETWORK_ERROR,
                message="Не удалось подключиться к серверу лицензий"
            )
            self._license_valid = False
            
        except Exception as e:
            logger.error(f"Неизвестная ошибка при проверке лицензии: {e}")
            result = LicenseCheckResult(
                status=LicenseStatus.SERVER_ERROR,
                message=f"Внутренняя ошибка: {str(e)}"
            )
            self._license_valid = False
            
        self._last_check_result = result
        return result
    
    def require_license(self) -> None:
        """
        Декоратор для функций, требующих действующей лицензии
        
        Raises:
            RuntimeError: если лицензия недействительна или сервер недоступен
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                # Проверяем лицензию перед выполнением
                result = self.check_license()
                
                if result.status != LicenseStatus.VALID:
                    error_msg = f"Функция '{func.__name__}' заблокирована. {result.message}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)
                
                # Лицензия действительна - выполняем функцию
                return func(*args, **kwargs)
            return wrapper
        return decorator


# Пример использования
def main():
    # Инициализация менеджера лицензий
    license_manager = LicenseManager(
        license_server_url="https://license.example.com",
        license_key="YOUR_LICENSE_KEY",
        timeout=5
    )
    
    # Декорирование функции, требующей лицензии
    @license_manager.require_license()
    def premium_feature():
        """Премиум-функция, требующая действующей лицензии"""
        print("Выполняется премиум-функция...")
        # Логика функции
        return "Результат премиум-функции"
    
    # Попытка выполнения функции
    try:
        result = premium_feature()
        print(f"Успех: {result}")
    except RuntimeError as e:
        print(f"Ошибка: {e}")


if __name__ == "__main__":
    main()