import httpx
import uuid
import logging
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PaymentGateway")

class PaymentStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"  # Статус для случаев таймаута
    TIMEOUT = "timeout_error"

class PaymentGatewayClient:
    """
    Клиент для взаимодействия с платежным шлюзом.
    Реализует строгую логику обработки сетевых задержек.
    """

    def __init__(self, api_url: str, api_key: str, timeout_sec: float = 10.0):
        self.api_url = api_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Request-ID": "" # Будет генерироваться для каждого запроса
        }
        self.timeout = timeout_sec

    def process_payment(self, amount: float, currency: str, card_data: Dict[str, str]) -> Dict[str, Any]:
        """
        Отправляет запрос на проведение платежа.
        """
        request_id = str(uuid.uuid4())
        self.headers["X-Request-ID"] = request_id

        payload = {
            "amount": amount,
            "currency": currency,
            "card": card_data,
            "timestamp": datetime.now().isoformat()
        }

        try:
            logger.info(f"[*] Отправка платежа {request_id} на сумму {amount} {currency}")
            
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.api_url}/v1/charge",
                    json=payload,
                    headers=self.headers
                )
                
                # Обработка успешного ответа от сервера
                response.raise_for_status()
                data = response.json()
                
                logger.info(f"[+] Платеж {request_id} успешно обработан шлюзом.")
                return {
                    "status": PaymentStatus.SUCCESS,
                    "transaction_id": data.get("id"),
                    "details": data
                }

        except httpx.TimeoutException:
            # САМЫЙ ВАЖНЫЙ БЛОК: Сервер не ответил вовремя.
            # Мы НЕ ЗНАЕМ, прошел платеж или нет. 
            # Ставим статус PENDING и отправляем на ручную проверку или poll-запрос.
            logger.error(f"[!] ТАЙМАУТ для транзакции {request_id}. Статус платежа не определен.")
            return {
                "status": PaymentStatus.PENDING,
                "request_id": request_id,
                "error": "Gateway timeout. Integrity check required.",
                "action_required": "verify_status_later"
            }

        except httpx.HTTPStatusError as e:
            # Ошибка на стороне банка (например, 402 Declined или 500)
            logger.warning(f"[-] Отказ банка для {request_id}: {e.response.text}")
            return {
                "status": PaymentStatus.FAILED,
                "error": f"Bank rejected: {e.response.status_code}",
                "details": e.response.json() if e.response.content else {}
            }

        except Exception as e:
            # Прочие сетевые ошибки (обрыв связи, DNS)
            logger.critical(f"[!] Системная ошибка связи: {str(e)}")
            return {
                "status": PaymentStatus.TIMEOUT,
                "error": "Network connectivity issue"
            }

# --- Пример использования ---

if __name__ == "__main__":
    # Настройки шлюза
    gateway = PaymentGatewayClient(
        api_url="https://api.stripe.com", # Пример
        api_key="sk_test_51Mz...",
        timeout_sec=5.0  # Устанавливаем жесткий лимит 5 секунд
    )

    result = gateway.process_payment(
        amount=2500.0,
        currency="RUB",
        card_data={"token": "tok_visa_debit"}
    )

    print(f"\nИтоговый статус: {result['status']}")
    if result['status'] == PaymentStatus.PENDING:
        print("ВНИМАНИЕ: Не блокируйте товар! Нужно проверить статус позже через GET /status.")