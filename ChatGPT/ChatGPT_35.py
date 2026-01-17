from dataclasses import dataclass
from typing import Any, Callable, Dict

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ValidationError


# ==================================================
# Исключения
# ==================================================

class WebhookProcessingError(Exception):
    """Базовая ошибка обработки вебхука."""


class UnknownEventTypeError(WebhookProcessingError):
    """Тип события не зарегистрирован."""


# ==================================================
# Доменные модели
# ==================================================

@dataclass(frozen=True)
class WebhookEvent:
    """
    Доменное представление вебхук-события.
    """
    event_type: str
    payload: Dict[str, Any]


# ==================================================
# API-схема входящих данных
# ==================================================

class WebhookRequest(BaseModel):
    """
    Строгая схема входящего вебхука.
    """
    event_type: str
    payload: Dict[str, Any]


# ==================================================
# Dispatcher
# ==================================================

class WebhookDispatcher:
    """
    Диспетчер вебхуков.
    Отвечает за маршрутизацию событий к обработчикам.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[WebhookEvent], None]] = {}

    def register_handler(
        self,
        event_type: str,
        handler: Callable[[WebhookEvent], None],
    ) -> None:
        """
        Регистрирует обработчик для конкретного типа события.
        """
        self._handlers[event_type] = handler

    def dispatch(self, event: WebhookEvent) -> None:
        """
        Вызывает соответствующий обработчик события.
        """
        handler = self._handlers.get(event.event_type)

        if not handler:
            raise UnknownEventTypeError(
                f"Handler for event '{event.event_type}' not found"
            )

        handler(event)


# ==================================================
# Обработчики событий (пример)
# ==================================================

def handle_user_created(event: WebhookEvent) -> None:
    user_id = event.payload.get("user_id")
    email = event.payload.get("email")

    # Здесь может быть запись в БД, очередь, логика бизнес-слоя
    print(f"[WEBHOOK] User created: id={user_id}, email={email}")


def handle_payment_completed(event: WebhookEvent) -> None:
    payment_id = event.payload.get("payment_id")
    amount = event.payload.get("amount")

    print(f"[WEBHOOK] Payment completed: id={payment_id}, amount={amount}")


# ==================================================
# FastAPI приложение
# ==================================================

app = FastAPI(title="Webhook Service")

dispatcher = WebhookDispatcher()
dispatcher.register_handler("user.created", handle_user_created)
dispatcher.register_handler("payment.completed", handle_payment_completed)


@app.post("/webhooks", status_code=status.HTTP_204_NO_CONTENT)
async def receive_webhook(request: Request) -> None:
    """
    Единая точка приёма вебхуков.
    """
    try:
        raw_body = await request.json()
        webhook_request = WebhookRequest(**raw_body)

        event = WebhookEvent(
            event_type=webhook_request.event_type,
            payload=webhook_request.payload,
        )

        dispatcher.dispatch(event)

    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload",
        ) from exc

    except UnknownEventTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        # Здесь можно подключить Sentry / логирование
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed",
        ) from exc
