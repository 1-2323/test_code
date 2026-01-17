import json
from typing import Any, Dict, Callable

from fastapi import FastAPI, Request, HTTPException, status
from pydantic import BaseModel, Field, ValidationError


# =========================
# CONFIGURATION
# =========================

ALLOWED_CONTENT_TYPES = {"application/json"}
ALLOWED_EVENT_TYPES = {"user.created", "order.paid", "order.canceled"}


# =========================
# EVENT SCHEMAS
# =========================

class BaseEvent(BaseModel):
    event_type: str = Field(..., alias="type")
    payload: Dict[str, Any]


class UserCreatedPayload(BaseModel):
    user_id: int
    email: str


class OrderPaidPayload(BaseModel):
    order_id: int
    amount: float


class OrderCanceledPayload(BaseModel):
    order_id: int
    reason: str


# =========================
# HANDLERS
# =========================

class WebhookHandlers:
    def handle_user_created(self, payload: UserCreatedPayload) -> None:
        # Изолированная логика обработки
        pass

    def handle_order_paid(self, payload: OrderPaidPayload) -> None:
        pass

    def handle_order_canceled(self, payload: OrderCanceledPayload) -> None:
        pass


# =========================
# DISPATCHER
# =========================

class WebhookDispatcher:
    def __init__(self) -> None:
        self._handlers = WebhookHandlers()
        self._routing: Dict[str, Callable[[Dict[str, Any]], None]] = {
            "user.created": self._dispatch_user_created,
            "order.paid": self._dispatch_order_paid,
            "order.canceled": self._dispatch_order_canceled,
        }

    def dispatch(self, raw_body: bytes, content_type: str) -> None:
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Неподдерживаемый формат данных",
            )

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Некорректная сериализация",
            )

        try:
            event = BaseEvent.model_validate(data)
        except ValidationError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Некорректная структура события",
            )

        if event.event_type not in ALLOWED_EVENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Недопустимый тип события",
            )

        handler = self._routing.get(event.event_type)
        if not handler:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Обработчик не найден",
            )

        try:
            handler(event.payload)
        except ValidationError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Некорректные данные события",
            )
        except Exception:
            # Изоляция обработчиков
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ошибка обработки события",
            )

    # =========================
    # INTERNAL ROUTES
    # =========================

    def _dispatch_user_created(self, payload: Dict[str, Any]) -> None:
        validated = UserCreatedPayload.model_validate(payload)
        self._handlers.handle_user_created(validated)

    def _dispatch_order_paid(self, payload: Dict[str, Any]) -> None:
        validated = OrderPaidPayload.model_validate(payload)
        self._handlers.handle_order_paid(validated)

    def _dispatch_order_canceled(self, payload: Dict[str, Any]) -> None:
        validated = OrderCanceledPayload.model_validate(payload)
        self._handlers.handle_order_canceled(validated)


# =========================
# FASTAPI APPLICATION
# =========================

app = FastAPI(title="Webhook Dispatcher")
dispatcher = WebhookDispatcher()


@app.post("/webhooks")
async def receive_webhook(request: Request) -> dict:
    content_type = request.headers.get("content-type", "").split(";")[0]
    raw_body = await request.body()

    dispatcher.dispatch(
        raw_body=raw_body,
        content_type=content_type,
    )

    return {"status": "accepted"}
