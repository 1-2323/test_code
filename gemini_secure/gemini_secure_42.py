import asyncio
import logging
import httpx
import time
from typing import Final, List, Dict, Optional
from pydantic import BaseModel, HttpUrl

# --- Конфигурация мониторинга ---
CHECK_INTERVAL: Final[int] = 60  # Интервал между проверками в секундах
MAX_RETRIES: Final[int] = 3      # Количество попыток перед отправкой уведомления
RETRY_DELAY: Final[int] = 5      # Задержка между повторными попытками при сбое
EXTERNAL_ALERTS_URL: Final[str] = "https://hooks.slack.com/services/T000/B000/XXXX"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("HealthMonitor")

class Node(BaseModel):
    """Модель узла для мониторинга."""
    name: str
    url: HttpUrl

class HealthCheckService:
    """Сервис мониторинга доступности узлов с защитой от ложных срабатываний."""

    def __init__(self, nodes: List[Node]):
        self.nodes = nodes
        self.client_options = {
            "timeout": 10.0,
            "follow_redirects": True
        }

    async def _send_alert(self, node_name: str, error_msg: str):
        """Отправка уведомления во внешний сервис (Slack/Telegram)."""
        payload = {
            "text": f"🚨 *CRITICAL ALERT*: Node `{node_name}` is DOWN!\nError: {error_msg}"
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(EXTERNAL_ALERTS_URL, json=payload)
                response.raise_for_status()
                logger.info(f"Alert sent for {node_name}")
        except Exception as e:
            logger.error(f"Failed to send alert to external service: {e}")

    async def _check_node_with_retry(self, node: Node) -> bool:
        """Проверяет узел и подтверждает сбой через серию попыток."""
        last_error = ""
        
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(**self.client_options) as client:
                    response = await client.get(str(node.url))
                    if response.status_code == 200:
                        if attempt > 1:
                            logger.info(f"Node {node.name} recovered on attempt {attempt}")
                        return True
                    
                    last_error = f"Status Code: {response.status_code}"
            except httpx.RequestError as e:
                last_error = str(e)

            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} for {node.name} failed: {last_error}")
            
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

        # Если все попытки исчерпаны, отправляем алерт
        await self._send_alert(node.name, last_error)
        return False

    async def run_forever(self):
        """Основной цикл мониторинга с контролем частоты проверок."""
        logger.info(f"Starting monitoring for {len(self.nodes)} nodes...")
        
        while True:
            start_time = time.time()
            
            # Запускаем проверки всех узлов параллельно
            tasks = [self._check_node_with_retry(node) for node in self.nodes]
            await asyncio.gather(*tasks)

            # Ограничение частоты: ждем оставшееся время до конца интервала
            elapsed = time.time() - start_time
            sleep_time = max(0, CHECK_INTERVAL - elapsed)
            
            logger.debug(f"Cycle finished. Sleeping for {sleep_time:.2f}s")
            await asyncio.sleep(sleep_time)

# --- Настройка узлов и запуск ---

critical_nodes = [
    Node(name="Main API", url="https://api.myservice.com/health"),
    Node(name="Database Gateway", url="https://db-proxy.internal.local/ping"),
]

if __name__ == "__main__":
    monitor = HealthCheckService(critical_nodes)
    try:
        asyncio.run(monitor.run_forever())
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user.")