import requests
from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict


# =========================
# CONFIGURATION
# =========================

PAYMENT_GATEWAY_URL = "https://bank.example.com/pay"
REQUEST_TIMEOUT_SECONDS = 5


# =========================
# EXCEPTIONS
# =========================

class PaymentError(RuntimeError):
    pass


class PaymentTimeoutError(PaymentError):
    pass


class PaymentRejectedError(PaymentError):
    pass


# =========================
# PAYMENT STATE
# =========================

class PaymentStatus(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


# =========================
# DATA MODELS
# =========================

@dataclass(frozen=True)
class PaymentRequest:
    payment_id: str
    amount: float
    currency: str
    token: str


@dataclass(frozen=True)
class PaymentResult:
    status: PaymentStatus
    transaction_id: str | None = None
    raw_response: Dict[str, Any] | None = None


# =========================
# CLIENT
# =========================

class PaymentGatewayClient:
    def __init__(self, gateway_url: str = PAYMENT_GATEWAY_URL) -> None:
        self._gateway_url = gateway_url

    def process_payment(self, request: PaymentRequest) -> PaymentResult:
        try:
            response = requests.post(
                self._gateway_url,
                json={
                    "payment_id": request.payment_id,
                    "amount": request.amount,
                    "currency": request.currency,
                },
                headers={
                    "Authorization": f"Bearer {request.token}",
                    "Content-Type": "application/json",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            # Платеж не считается успешным при таймауте
            raise PaymentTimeoutError("Payment gateway did not respond in time") from exc
        except requests.RequestException as exc:
            raise PaymentError("Network error while contacting payment gateway") from exc

        if response.status_code != 200:
            raise PaymentRejectedError(
                f"Payment rejected with HTTP status {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentError("Invalid JSON response from payment gateway") from exc

        return self._parse_success_response(payload)

    # =========================
    # INTERNALS
    # =========================

    @staticmethod
    def _parse_success_response(payload: Dict[str, Any]) -> PaymentResult:
        if not isinstance(payload, dict):
            raise PaymentError("Malformed payment response")

        if payload.get("status") != "approved":
            raise PaymentRejectedError("Payment was not approved by bank")

        transaction_id = payload.get("transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id:
            raise PaymentError("Missing transaction ID in success response")

        return PaymentResult(
            status=PaymentStatus.SUCCESS,
            transaction_id=transaction_id,
            raw_response=payload,
        )
