import httpx
import uuid
import logging
from enum import Enum
from typing import Final, Optional
from pydantic import BaseModel, Field

# --- Состояния платежа ---

class PaymentStatus(str, Enum):
    INITIATED = "initiated"    # Запрос отправлен
    PENDING = "pending"        # Ответ не получен (таймаут/сетевая ошибка)
    SUCCESS = "success"        # Подтверждено банком
    FAILED = "failed"          # Отклонено банком
    UNKNOWN = "unknown"        # Неопределенное состояние

class PaymentResponse(BaseModel):
    transaction_id: str
    status: PaymentStatus
    bank_reference: Optional[str] = None
    error_detail: Optional[str] = None

# --- Клиент шлюза ---

class PaymentGatewayClient:
    """Клиент с жестким контролем таймаутов и состояний."""

    # Четкие лимиты на ожидание ответа от банка
    CONNECT_TIMEOUT: Final[float] = 3.0
    READ_TIMEOUT: Final[float] = 15.0  # Банковские шлюзы могут быть медленными

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.headers = {"Authorization": f"Bearer {api_key}", "X-Request-ID": ""}
        self.logger = logging.getLogger("PaymentClient")

    async def process_payment(self, amount: float, currency: str) -> PaymentResponse:
        """
        Отправляет запрос на платеж и строго обрабатывает жизненный цикл ответа.
        """
        idempotency_key = str(uuid.uuid4())
        self.headers["X-Request-ID"] = idempotency_key

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.READ_TIMEOUT, connect=self.CONNECT_TIMEOUT)
            ) as client:
                
                # 1. Состояние: Отправка запроса
                response = await client.post(
                    f"{self.api_url}/charge",
                    json={"amount": amount, "currency": currency},
                    headers=self.headers
                )

                # 2. Анализ HTTP-статуса
                if response.status_code == 200:
                    data = response.json()
                    if data.get("confirmed"):
                        return PaymentResponse(
                            transaction_id=idempotency_key,
                            status=PaymentStatus.SUCCESS,
                            bank_reference=data.get("ref")
                        )
                    return PaymentResponse(
                        transaction_id=idempotency_key,
                        status=PaymentStatus.FAILED,
                        error_detail="Bank declined transaction"
                    )
                
                # При 5xx ошибках — статус PENDING, так как банк мог обработать платеж
                return PaymentResponse(
                    transaction_id=idempotency_key,
                    status=PaymentStatus.PENDING,
                    error_detail=f"Server error: {response.status_code}"
                )

        except (httpx.ReadTimeout, httpx.ConnectTimeout):
            # КРИТИЧНО: При таймауте помечаем как PENDING. 
            # Нельзя считать это ошибкой или успехом без проверки.
            self.logger.warning(f"Timeout for TX {idempotency_key}. Moving to PENDING.")
            return PaymentResponse(
                transaction_id=idempotency_key,
                status=PaymentStatus.PENDING,
                error_detail="Timeout exceeded. Status synchronization required."
            )

        except httpx.RequestError as e:
            # Сетевые сбои до получения ответа
            return PaymentResponse(
                transaction_id=idempotency_key,
                status=PaymentStatus.PENDING,
                error_detail=f"Network error: {str(e)}"
            )