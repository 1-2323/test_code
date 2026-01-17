import json
import logging
from typing import Dict, Any, Callable, Final, Type
from pydantic import BaseModel, Field, ValidationError

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebhookDispatcher")

# --- Схемы данных (Белый список событий) ---

class WebhookEvent(BaseModel):
    """Базовая схема для всех входящих вебхуков."""
    event_type: str = Field(..., pattern=r"^[a-z_.]+$")
    payload: Dict[str, Any]
    timestamp: int

class OrderCreatedPayload(BaseModel):
    order_id: str
    amount: float

class UserSignupPayload(BaseModel):
    user_id: str
    email: str

# --- Диспетчер событий ---

class WebhookDispatcher:
    """
    Система обработки вебхуков с безопасной десериализацией 
    и изоляцией обработчиков.
    """

    def __init__(self):
        # Реестр разрешенных обработчиков: event_type -> (handler_func, schema)
        self._handlers: Dict[str, tuple[Callable, Type[BaseModel]]] = {}

    def register_handler(self, event_type: str, schema: Type[BaseModel]):
        """Декоратор для регистрации новых типов событий."""
        def decorator(func: Callable):
            self._handlers[event_type] = (func, schema)
            return func
        return decorator

    async def dispatch(self, raw_data: str | bytes):
        """
        Принимает сырые данные, безопасно десериализует и вызывает обработчик.
        """
        try:
            # 1. Безопасная десериализация (JSON вместо Pickle)
            # JSON не исполняет код при загрузке.
            data = json.loads(raw_data)
            
            # 2. Первичная валидация структуры
            envelope = WebhookEvent(**data)
            
            # 3. Проверка типа события по белому списку
            if envelope.event_type not in self._handlers:
                logger.warning(f"Unsupported event type: {envelope.event_type}")
                return

            handler_func, payload_schema = self._handlers[envelope.event_type]

            # 4. Валидация полезной нагрузки (Payload) перед обработкой
            validated_payload = payload_schema(**envelope.payload)

            # 5. Изолированный вызов обработчика
            # Ошибки в одном обработчике не должны останавливать всю систему.
            try:
                await handler_func(validated_payload)
            except Exception as e:
                logger.error(f"Error in handler '{envelope.event_type}': {str(e)}")

        except (json.JSONDecodeError, TypeError):
            logger.error("Invalid data format: Failed to parse JSON")
        except ValidationError as e:
            logger.error(f"Schema validation failed: {e.json()}")

# --- Реализация обработчиков ---

dispatcher = WebhookDispatcher()

@dispatcher.register_handler("order.created", OrderCreatedPayload)
async def handle_order_created(payload: OrderCreatedPayload):
    """Изолированный обработчик создания заказа."""
    logger.info(f"Processing order: {payload.order_id} for sum {payload.amount}")

@dispatcher.register_handler("user.signup", UserSignupPayload)
async def handle_user_signup(payload: UserSignupPayload):
    """Изолированный обработчик регистрации пользователя."""
    logger.info(f"New user registered: {payload.email}")