import sys
from dataclasses import dataclass
from typing import Any, Dict

import requests


CONFIG_API_URL = "https://config.example.com/app-config"
REQUEST_TIMEOUT_SECONDS = 5


class ConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class AppConfig:
    debug: bool
    log_level: str
    allowed_hosts: list[str]


class RemoteConfigLoader:
    def __init__(self, api_url: str) -> None:
        self._api_url = api_url

    def load(self) -> AppConfig:
        data = self._fetch_config()
        return self._validate(data)

    def _fetch_config(self) -> Dict[str, Any]:
        try:
            response = requests.get(
                self._api_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise ConfigurationError(
                f"Failed to load remote configuration: {exc}"
            ) from exc

    def _validate(self, data: Dict[str, Any]) -> AppConfig:
        try:
            return AppConfig(
                debug=bool(data["debug"]),
                log_level=str(data["log_level"]),
                allowed_hosts=list(data["allowed_hosts"]),
            )
        except Exception as exc:
            raise ConfigurationError(
                f"Invalid configuration schema: {exc}"
            ) from exc


def terminate_application(reason: str) -> None:
    print(f"APPLICATION TERMINATED: {reason}")
    sys.exit(1)


def main() -> None:
    loader = RemoteConfigLoader(CONFIG_API_URL)

    try:
        config = loader.load()
    except ConfigurationError as exc:
        terminate_application(str(exc))

    print("Configuration loaded securely")
    print(config)


if __name__ == "__main__":
    main()
