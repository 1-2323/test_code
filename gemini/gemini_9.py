import logging
import time
import uuid
from typing import Any, Dict, Optional
import httpx

# Настройка кастомного логгера
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PaymentGatewayClient")

class ExternalApiClient:
    """
    Клиент для интеграции с платежным шлюзом.
    Поддерживает авторизацию через Bearer Token, логирование сессий 
    и обработку ошибок протокола JSON.
    """

    def __init__(self, base_url: str, api_token: str, timeout: int = 10):
        """
        :param base_url: Базовый адрес API (например, https://api.gateway.com/v1)
        :param api_token: Ключ доступа для заголовка Authorization
        :param timeout: Время ожидания ответа в секундах
        """
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PaymentService-PythonClient/1.0"
        }
        self.timeout = timeout

    def _log_session(self, session_id: str, method: str, endpoint: str, 
                     payload: Optional[Dict], status_code: Optional[int] = None, 
                     duration: float = 0.0, error: Optional[str] = None) -> None:
        """
        Кастомное логирование сессии запроса.
        """
        log_msg = (
            f"[Session: {session_id}] {method} {endpoint} | "
            f"Status: {status_code} | Duration: {duration:.3f}s"
        )
        if error:
            logger.error(f"{log_msg} | Error: {error}")
        else:
            logger.info(log_msg)
            logger.debug(f"[Session: {session_id}] Payload: {payload}")

    async def post_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправляет POST-запрос к платежному шлюзу.
        
        Логика работы:
        1. Генерация уникального ID сессии (Correlation ID).
        2. Выполнение асинхронного запроса с обработкой таймаутов.
        3. Валидация JSON-ответа.
        4. Логирование результатов и ошибок.
        """
        session_id = str(uuid.uuid4())[:8]
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        start_time = time.monotonic()
        
        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
            try:
                response = await client.post(url, json=data)
                duration = time.monotonic() - start_time
                
                # Логируем успешную попытку (даже если статус 4xx/5xx)
                self._log_session(session_id, "POST", endpoint, data, 
                                  response.status_code, duration)
                
                # Проверка на HTTP ошибки (поднимает исключение httpx.HTTPStatusError)
                response.raise_for_status()
                
                return response.json()

            except httpx.HTTPStatusError as exc:
                duration = time.monotonic() - start_time
                self._log_session(session_id, "POST", endpoint, data, 
                                  exc.response.status_code, duration, str(exc))
                return {"error": "http_error", "message": str(exc), "details": exc.response.text}
                
            except httpx.RequestError as exc:
                duration = time.monotonic() - start_time
                self._log_session(session_id, "POST", endpoint, data, 
                                  None, duration, f"Network error: {str(exc)}")
                raise ConnectionError(f"Не удалось связаться с платежным шлюзом: {exc}")
            
            except Exception as exc:
                self._log_session(session_id, "POST", endpoint, data, None, 0, str(exc))
                raise

# --- Пример использования ---

async def main():
    # Данные для инициализации (обычно из env)
    GATEWAY_URL = "https://sandbox.payments.example.com"
    API_KEY = "pt_live_550e8400e29b41d4a716446655440000"

    client = ExternalApiClient(GATEWAY_URL, API_KEY)

    # Данные транзакции
    payment_payload = {
        "amount": 1500,
        "currency": "USD",
        "order_id": "ORDER-999",
        "payment_method": "card_token_123"
    }

    try:
        print("Отправка платежа...")
        result = await client.post_request("/payments/create", payment_payload)
        print(f"Ответ шлюза: {result}")
    except Exception as e:
        print(f"Критический сбой интеграции: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())