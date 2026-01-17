import sys
import requests
from dataclasses import dataclass
from typing import Any, Dict


# =========================
# CONFIGURATION
# =========================

CONFIG_API_URL = "https://config.example.com/runtime-config"
REQUEST_TIMEOUT_SECONDS = 5


# =========================
# EXCEPTIONS
# =========================

class ConfigurationError(RuntimeError):
    pass


# =========================
# DATA MODEL
# =========================

@dataclass(frozen=True)
class AppConfig:
    environment: str
    debug: bool
    database_url: str
    secret_key: str

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "AppConfig":
        required_fields = {
            "environment": str,
            "debug": bool,
            "database_url": str,
            "secret_key": str,
        }

        for field, expected_type in required_fields.items():
            if field not in payload:
                raise ConfigurationError(f"Missing configuration field: {field}")
            if not isinstance(payload[field], expected_type):
                raise ConfigurationError(
                    f"Invalid type for field '{field}': "
                    f"expected {expected_type.__name__}"
                )

        if payload["environment"] not in {"development", "production"}:
            raise ConfigurationError("Unsupported environment value")

        if len(payload["secret_key"]) < 32:
            raise ConfigurationError("Secret key is too short")

        return AppConfig(
            environment=payload["environment"],
            debug=payload["debug"],
            database_url=payload["database_url"],
            secret_key=payload["secret_key"],
        )


# =========================
# CONFIG LOADER
# =========================

class RemoteConfigLoader:
    @staticmethod
    def load() -> AppConfig:
        try:
            response = requests.get(
                CONFIG_API_URL,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ConfigurationError(
                f"Failed to connect to configuration service: {exc}"
            ) from exc

        if response.status_code != 200:
            raise ConfigurationError(
                f"Configuration service returned HTTP {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ConfigurationError("Invalid JSON received from config service") from exc

        if not isinstance(payload, dict):
            raise ConfigurationError("Configuration payload must be a JSON object")

        return AppConfig.from_dict(payload)


# =========================
# APPLICATION BOOTSTRAP
# =========================

def bootstrap_application() -> AppConfig:
    try:
        config = RemoteConfigLoader.load()
    except ConfigurationError as exc:
        print(f"[FATAL] Application startup aborted: {exc}", file=sys.stderr)
        sys.exit(1)

    return config


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":
    app_config = bootstrap_application()
    print("[INFO] Configuration loaded successfully")
    print(app_config)
