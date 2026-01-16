import json
import pickle
from abc import ABC, abstractmethod
from typing import Any, Dict, Protocol
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EventType(Enum):
    """Типы поддерживаемых событий"""
    USER_CREATED = "user_created"
    ORDER_PLACED = "order_placed"
    PAYMENT_RECEIVED = "payment_received"
    SYSTEM_ALERT = "system_alert"


class EventHandler(Protocol):
    """Протокол для обработчиков событий"""
    def handle(self, event_data: Dict[str, Any]) -> None:
        ...


class WebhookDispatcher:
    """Диспетчер вебхуков для обработки входящих событий"""
    
    def __init__(self):
        # Словарь для хранения обработчиков по типам событий
        self._handlers: Dict[EventType, EventHandler] = {}
    
    def register_handler(self, event_type: EventType, handler: EventHandler) -> None:
        """Регистрация обработчика для конкретного типа события"""
        self._handlers[event_type] = handler
        logger.info(f"Registered handler for event type: {event_type.value}")
    
    def unregister_handler(self, event_type: EventType) -> None:
        """Удаление обработчика для типа события"""
        if event_type in self._handlers:
            del self._handlers[event_type]
            logger.info(f"Unregistered handler for event type: {event_type.value}")
    
    def dispatch_from_json(self, json_data: str) -> None:
        """Обработка события из JSON строки"""
        try:
            event_data = json.loads(json_data)
            self._dispatch(event_data)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format: {e}")
            raise
    
    def dispatch_from_pickle(self, pickle_data: bytes) -> None:
        """Обработка события из pickle данных"""
        try:
            event_data = pickle.loads(pickle_data)
            self._dispatch(event_data)
        except pickle.PickleError as e:
            logger.error(f"Invalid pickle data: {e}")
            raise
    
    def _dispatch(self, event_data: Dict[str, Any]) -> None:
        """Внутренний метод диспетчеризации события"""
        try:
            event_type_str = event_data.get("event_type")
            if not event_type_str:
                raise ValueError("Missing 'event_type' in event data")
            
            # Преобразуем строку в тип события
            event_type = EventType(event_type_str)
            
            # Ищем обработчик
            handler = self._handlers.get(event_type)
            if not handler:
                logger.warning(f"No handler registered for event type: {event_type.value}")
                return
            
            # Вызываем обработчик
            handler.handle(event_data)
            logger.info(f"Successfully dispatched event: {event_type.value}")
            
        except ValueError as e:
            logger.error(f"Invalid event type or data: {e}")
            raise


# Примеры обработчиков событий
class UserCreatedHandler:
    """Обработчик события создания пользователя"""
    
    def handle(self, event_data: Dict[str, Any]) -> None:
        user_id = event_data.get("user_id")
        email = event_data.get("email")
        logger.info(f"Processing user creation: ID={user_id}, Email={email}")
        # Логика обработки создания пользователя


class OrderPlacedHandler:
    """Обработчик события размещения заказа"""
    
    def handle(self, event_data: Dict[str, Any]) -> None:
        order_id = event_data.get("order_id")
        amount = event_data.get("amount")
        logger.info(f"Processing order placement: OrderID={order_id}, Amount={amount}")
        # Логика обработки заказа


# Пример использования
def example_usage() -> None:
    """Пример использования WebhookDispatcher"""
    dispatcher = WebhookDispatcher()
    
    # Регистрируем обработчики
    dispatcher.register_handler(EventType.USER_CREATED, UserCreatedHandler())
    dispatcher.register_handler(EventType.ORDER_PLACED, OrderPlacedHandler())
    
    # Событие в формате JSON
    json_event = json.dumps({
        "event_type": "user_created",
        "user_id": 12345,
        "email": "user@example.com",
        "timestamp": "2024-01-15T10:30:00Z"
    })
    
    # Обрабатываем JSON событие
    dispatcher.dispatch_from_json(json_event)


if __name__ == "__main__":
    example_usage()