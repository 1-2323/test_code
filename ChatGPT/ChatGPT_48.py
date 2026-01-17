import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import requests


PAYMENT_API_URL = "https://bank.example.com/pay"
REQUEST_TIMEOUT_SECONDS = 5


class PaymentStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class PaymentError(Exception):
    pass


@dataclass(frozen=True)
class PaymentResult:
    status: PaymentStatus
    transaction_id: Optional[str]
    message: str


class PaymentGatewayClient:
    def __init__(self, api_url: str, api_token: str) -> None:
        self._api_url = api_url
        self._api_token = api_token

    def make_payment(
        self,
        amount: float,
        currency: str,
        order_id: str,
    ) -> PaymentResult:
        payload = {
            "order_id": order_id,
            "amount": amount,
            "currency": currency,
        }

        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self._api_url,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_response(data)
        except requests.Timeout:
            return PaymentResult(
                status=PaymentStatus.TIMEOUT,
                transaction_id=None,
                message="Payment status unknown: bank timeout",
            )
        except Exception as exc:
            return PaymentResult(
                status=PaymentStatus.FAILED,
                transaction_id=None,
                message=str(exc),
            )

    def _parse_response(self, data: Dict[str, Any]) -> PaymentResult:
        if data.get("status") == "approved":
            return PaymentResult(
                status=PaymentStatus.SUCCESS,
                transaction_id=str(data.get("transaction_id")),
                message="Payment approved",
            )

        return PaymentResult(
            status=PaymentStatus.FAILED,
            transaction_id=str(data.get("transaction_id")),
            message=str(data.get("message", "Payment rejected")),
        )


def main() -> None:
    client = PaymentGatewayClient(
        api_url=PAYMENT_API_URL,
        api_token="PAYMENT_API_TOKEN",
    )

    result = client.make_payment(
        amount=100.0,
        currency="USD",
        order_id=str(int(time.time())),
    )

    print(result)


if __name__ == "__main__":
    main()
