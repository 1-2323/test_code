import asyncio
import httpx
import logging
import socket
from datetime import datetime
from typing import List, Dict

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("Sentinel")

class ServiceSentinel:
    """
    Монитор доступности инфраструктуры с системой алертинга.
    """

    def __init__(self, tg_token: str, tg_chat_id: str):
        self.tg_token = tg_token
        self.tg_chat_id = tg_chat_id
        self.tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"

    async def send_alert(self, service_name: str, error_msg: str):
        """Отправляет уведомление о сбое в Telegram."""
        message = (
            f"🚨 **ALARM: Service Down!**\n"
            f"**Узел:** {service_name}\n"
            f"**Ошибка:** `{error_msg}`\n"
            f"**Время:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        try:
            async with httpx.AsyncClient() as client:
                await client.post(self.tg_url, json={
                    "chat_id": self.tg_chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                })
            logger.info(f"Уведомление о сбое {service_name} отправлено.")
        except Exception as e:
            logger.error(f"Не удалось отправить алерт: {e}")

    async def check_http(self, name: str, url: str) -> bool:
        """Проверяет доступность API через HTTP GET."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    logger.info(f"✅ {name}: OK")
                    return True
                raise Exception(f"Status Code: {response.status_code}")
        except Exception as e:
            error_text = str(e)
            logger.error(f"❌ {name}: DOWN ({error_text})")
            await self.send_alert(name, error_text)
            return False

    async def check_tcp(self, name: str, host: str, port: int) -> bool:
        """Проверяет доступность БД или сервиса через TCP-сокет."""
        try:
            # Пытаемся открыть соединение за короткий таймаут
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), 
                timeout=3.0
            )
            writer.close()
            await writer.wait_closed()
            logger.info(f"✅ {name} (TCP): OK")
            return True
        except Exception as e:
            error_text = f"Connection failed on {host}:{port}"
            logger.error(f"❌ {name}: DOWN")
            await self.send_alert(name, error_text)
            return False

    async def run_forever(self, interval: int = 60):
        """Запускает бесконечный цикл мониторинга."""
        services = [
            {"type": "http", "name": "Main API", "url": "https://api.myapp.com/health"},
            {"type": "tcp", "name": "PostgreSQL", "host": "127.0.0.1", "port": 5432},
            {"type": "tcp", "name": "Redis Cache", "host": "127.0.0.1", "port": 6379}
        ]

        logger.info("Sentinel запущен. Начало мониторинга...")
        while True:
            tasks = []
            for s in services:
                if s["type"] == "http":
                    tasks.append(self.check_http(s["name"], s["url"]))
                else:
                    tasks.append(self.check_tcp(s["name"], s["host"], s["port"]))
            
            await asyncio.gather(*tasks)
            await asyncio.sleep(interval)

# --- Запуск скрипта ---

if __name__ == "__main__":
    # Данные для Telegram (взять у @BotFather)
    TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    CHAT_ID = "987654321"

    sentinel = ServiceSentinel(TOKEN, CHAT_ID)
    
    try:
        asyncio.run(sentinel.run_forever(interval=30))
    except KeyboardInterrupt:
        logger.info("Мониторинг остановлен пользователем.")