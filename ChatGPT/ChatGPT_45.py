import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests


LICENSE_SERVER_URL = "https://license.example.com/verify"
REQUEST_TIMEOUT_SECONDS = 5
CACHE_TTL_SECONDS = 300


class LicenseError(Exception):
    pass


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    message: str


class LicenseClient:
    def __init__(self, server_url: str, api_key: str) -> None:
        self._server_url = server_url
        self._api_key = api_key
        self._cached_status: Optional[LicenseStatus] = None
        self._cache_expires_at: float = 0.0

    def verify(self) -> LicenseStatus:
        now = time.time()
        if self._cached_status and now < self._cache_expires_at:
            return self._cached_status

        try:
            response = requests.post(
                self._server_url,
                json={"api_key": self._api_key},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise LicenseError(f"License server unavailable: {exc}") from exc

        status = LicenseStatus(
            valid=bool(payload.get("valid")),
            message=str(payload.get("message", "")),
        )

        if not status.valid:
            raise LicenseError(status.message or "License verification failed")

        self._cached_status = status
        self._cache_expires_at = now + CACHE_TTL_SECONDS
        return status


class LicenseGuard:
    def __init__(self, client: LicenseClient) -> None:
        self._client = client

    def protected(self, func: Callable[..., None]) -> Callable[..., None]:
        def wrapper(*args, **kwargs):
            self._client.verify()
            return func(*args, **kwargs)
        return wrapper


def block_application(reason: str) -> None:
    print(f"APPLICATION BLOCKED: {reason}")
    sys.exit(1)


def main() -> None:
    api_key = "APPLICATION_LICENSE_KEY"
    client = LicenseClient(LICENSE_SERVER_URL, api_key)
    guard = LicenseGuard(client)

    try:
        client.verify()
    except LicenseError as exc:
        block_application(str(exc))

    @guard.protected
    def critical_function() -> None:
        print("Critical function executed")

    critical_function()


if __name__ == "__main__":
    main()
