import json
import logging
from typing import Callable, Dict, Any, Optional

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebhookDispatcher")

class WebhookDispatcher:
    """
    Диспетчер входящих вебхуков.
    Регистрирует обработчики для различных типов событий и координирует их вызов.
    """

    def __init__(self):
        # Словарь соответствия: { "event_type": callback_function }
        self._handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {}

    def register_handler(self, event_type: str):
        """
        Декоратор для регистрации функций-обработчиков.
        """
        def decorator(func: Callable):
            self._handlers[event_type] = func
            return func
        return decorator

    async def process_payload(self, raw_payload: str) -> bool:
        """
        Принимает сериализованный JSON, определяет тип события и вызывает метод.
        """
        try:
            # 1. Десериализация (безопасный JSON)
            data = json.loads(raw_payload)
            
            # 2. Определение типа события (предполагаем поле 'event')
            event_type = data.get("event")
            if not event_type:
                logger.error("Payload не содержит обязательного поля 'event'.")
                return False

            # 3. Поиск и вызов обработчика
            handler = self._handlers.get(event_type)
            if handler:
                logger.info(f"Запуск обработки события: {event_type}")
                # Вызов метода обработки (можно сделать асинхронным через await)
                handler(data)
                return True
            else:
                logger.warning(f"Обработчик для события '{event_type}' не зарегистрирован.")
                return False

        except json.JSONDecodeError:
            logger.error("Ошибка десериализации: передан некорректный JSON.")
            return False
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при обработке вебхука: {e}")
            return False

# --- Использование диспетчера ---

dispatcher = WebhookDispatcher()

@dispatcher.register_handler("payment.success")
def handle_payment(payload: Dict[str, Any]):
    """Обработчик успешной оплаты."""
    amount = payload.get("data", {}).get("amount")
    print(f"--- [Payment Success] Сумма: {amount} ---")

@dispatcher.register_handler("user.registered")
def handle_registration(payload: Dict[str, Any]):
    """Обработчик регистрации пользователя."""
    email = payload.get("data", {}).get("email")
    print(f"--- [User Registered] Отправка приветствия на {email} ---")

# --- Имитация работы с FastAPI/Flask ---

async def simulate_webhook():
    # Пример входящих данных от внешнего сервиса
    payload_1 = '{"event": "payment.success", "data": {"amount": 5000, "currency": "RUB"}}'
    payload_2 = '{"event": "user.registered", "data": {"email": "test@example.com"}}'
    
    print("Входящий поток вебхуков...")
    await dispatcher.process_payload(payload_1)
    await dispatcher.process_payload(payload_2)

if __name__ == "__main__":
    import asyncio
    asyncio.run(simulate_webhook())