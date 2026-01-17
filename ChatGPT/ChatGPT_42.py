import socket
import time
from dataclasses import dataclass
from typing import Callable, List

import requests


# ==================================================
# Конфигурация
# ==================================================

CHECK_INTERVAL_SECONDS = 30
DEFAULT_TIMEOUT = 5


# ==================================================
# Исключения
# ==================================================

class MonitoringError(Exception):
    """Ошибка мониторинга."""


# ==================================================
# Уведомления (Telegram)
# ==================================================

class TelegramNotifier:
    """
    Отправляет уведомления в Telegram.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def notify(self, message: str) -> None:
        try:
            requests.post(
                self._api_url,
                json={
                    "chat_id": self._chat_id,
                    "text": message,
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException:
            # Уведомление не должно ломать мониторинг
            print("[WARN] Failed to send Telegram notification")


# ==================================================
# Проверяемый узел
# ==================================================

@dataclass(frozen=True)
class NodeCheck:
    name: str
    check: Callable[[], None]


# ==================================================
# Проверки доступности
# ==================================================

def check_http(url: str) -> None:
    response = requests.get(url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()


def check_tcp(host: str, port: int) -> None:
    with socket.create_connection((host, port), timeout=DEFAULT_TIMEOUT):
        pass


# ==================================================
# Монитор
# ==================================================

class AvailabilityMonitor:
    """
    Монитор доступности критических узлов.
    """

    def __init__(
        self,
        nodes: List[NodeCheck],
        notifier: TelegramNotifier,
    ) -> None:
        self._nodes = nodes
        self._notifier = notifier

    def run(self) -> None:
        print("[INFO] Availability monitor started")

        while True:
            for node in self._nodes:
                try:
                    node.check()
                    print(f"[OK] {node.name} is available")
                except Exception as exc:
                    self._handle_failure(node.name, exc)

            time.sleep(CHECK_INTERVAL_SECONDS)

    def _handle_failure(self, node_name: str, error: Exception) -> None:
        message = (
            f"🚨 SERVICE DOWN\n"
            f"Node: {node_name}\n"
            f"Error: {error}"
        )

        print(message)
        self._notifier.notify(message)


# ==================================================
# Запуск
# ==================================================

if __name__ == "__main__":
    # 🔐 Реальные значения
    TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
    TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

    notifier = TelegramNotifier(
        bot_token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
    )

    nodes = [
        NodeCheck(
            name="Main API",
            check=lambda: check_http("https://api.example.com/health"),
        ),
        NodeCheck(
            name="PostgreSQL",
            check=lambda: check_tcp("127.0.0.1", 5432),
        ),
        NodeCheck(
            name="Redis",
            check=lambda: check_tcp("127.0.0.1", 6379),
        ),
    ]

    monitor = AvailabilityMonitor(nodes, notifier)
    monitor.run()
