import time
import socket
import requests
from dataclasses import dataclass
from typing import Callable, List, Optional


# =========================
# CONFIGURATION
# =========================

CHECK_INTERVAL_SECONDS = 30          # минимальный интервал между проверками
FAILURE_THRESHOLD = 3                # количество подряд неудачных проверок
CONNECTION_TIMEOUT = 5               # таймаут сетевых операций
NOTIFICATION_TIMEOUT = 10

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/REPLACE/ME"


# =========================
# DATA MODELS
# =========================

@dataclass(frozen=True)
class MonitoredNode:
    name: str
    check_function: Callable[[], bool]


# =========================
# NOTIFICATION SERVICE
# =========================

class AlertNotifier:
    @staticmethod
    def notify(message: str) -> None:
        payload = {"text": message}

        try:
            requests.post(
                SLACK_WEBHOOK_URL,
                json=payload,
                timeout=NOTIFICATION_TIMEOUT,
            )
        except requests.RequestException:
            # Уведомление не должно ломать основной мониторинг
            pass


# =========================
# CHECK FUNCTIONS
# =========================

def check_tcp_service(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CONNECTION_TIMEOUT):
            return True
    except (socket.timeout, OSError):
        return False


def check_http_endpoint(url: str) -> bool:
    try:
        response = requests.get(url, timeout=CONNECTION_TIMEOUT)
        return response.status_code < 500
    except requests.RequestException:
        return False


# =========================
# MONITOR CORE
# =========================

class AvailabilityMonitor:
    def __init__(self, nodes: List[MonitoredNode]) -> None:
        self._nodes = nodes
        self._failure_counters: dict[str, int] = {node.name: 0 for node in nodes}
        self._alerted: set[str] = set()

    def run(self) -> None:
        while True:
            for node in self._nodes:
                self._check_node(node)

            time.sleep(CHECK_INTERVAL_SECONDS)

    def _check_node(self, node: MonitoredNode) -> None:
        is_available = False

        try:
            is_available = node.check_function()
        except Exception:
            is_available = False

        if is_available:
            self._failure_counters[node.name] = 0
            self._alerted.discard(node.name)
            return

        self._failure_counters[node.name] += 1
        print(f"[WARN] {node.name} check failed ({self._failure_counters[node.name]})")

        if (
            self._failure_counters[node.name] >= FAILURE_THRESHOLD
            and node.name not in self._alerted
        ):
            self._alerted.add(node.name)
            self._send_alert(node)

    def _send_alert(self, node: MonitoredNode) -> None:
        message = (
            f"🚨 CRITICAL NODE UNAVAILABLE\n"
            f"Node: {node.name}\n"
            f"Failures: {self._failure_counters[node.name]}"
        )

        print(message)
        AlertNotifier.notify(message)


# =========================
# SETUP
# =========================

if __name__ == "__main__":
    monitored_nodes = [
        MonitoredNode(
            name="Primary Database",
            check_function=lambda: check_tcp_service("127.0.0.1", 5432),
        ),
        MonitoredNode(
            name="Public API",
            check_function=lambda: check_http_endpoint("https://api.example.com/health"),
        ),
    ]

    monitor = AvailabilityMonitor(monitored_nodes)
    monitor.run()
