import json
import logging
from functools import wraps
from typing import Dict, Any, Optional, Callable

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Whitelist разрешенных действий
ALLOWED_ACTIONS = {
    'user_registered',
    'order_created',
    'payment_processed',
    'subscription_canceled',
    'support_ticket_created'
}

# Хранилище обработчиков действий
_action_handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

def webhook_action(action_name: str):
    """Декоратор для регистрации обработчиков действий"""
    def decorator(func: Callable[[Dict[str, Any]], Dict[str, Any]]):
        if action_name not in ALLOWED_ACTIONS:
            raise ValueError(f"Действие '{action_name}' не в whitelist")
        
        _action_handlers[action_name] = func
        return func
    return decorator

def validate_webhook_payload(required_fields: list):
    """Декоратор для валидации входящих данных"""
    def decorator(func):
        @wraps(func)
        def wrapper(payload: Dict[str, Any]) -> Dict[str, Any]:
            missing_fields = []
            for field in required_fields:
                if field not in payload:
                    missing_fields.append(field)
            
            if missing_fields:
                return {
                    'status': 'error',
                    'message': f'Отсутствуют обязательные поля: {missing_fields}'
                }
            
            return func(payload)
        return wrapper
    return decorator

# Регистрация обработчиков действий
@webhook_action('user_registered')
@validate_webhook_payload(['user_id', 'email', 'timestamp'])
def handle_user_registered(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик регистрации пользователя"""
    logger.info(f"Пользователь зарегистрирован: {payload['user_id']}")
    
    # Бизнес-логика
    user_data = {
        'id': payload['user_id'],
        'email': payload['email'],
        'welcome_email_sent': True,
        'segment': 'new_user'
    }
    
    return {
        'status': 'success',
        'action': 'user_registered',
        'processed_data': user_data
    }

@webhook_action('order_created')
@validate_webhook_payload(['order_id', 'customer_id', 'amount', 'currency'])
def handle_order_created(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик создания заказа"""
    logger.info(f"Заказ создан: {payload['order_id']}")
    
    # Бизнес-логика
    order_summary = {
        'order_id': payload['order_id'],
        'total': payload['amount'],
        'currency': payload['currency'],
        'inventory_reserved': True,
        'confirmation_sent': True
    }
    
    return {
        'status': 'success',
        'action': 'order_created',
        'processed_data': order_summary
    }

@webhook_action('payment_processed')
@validate_webhook_payload(['payment_id', 'order_id', 'status', 'amount'])
def handle_payment_processed(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик завершенного платежа"""
    logger.info(f"Платеж обработан: {payload['payment_id']}")
    
    # Бизнес-логика
    payment_data = {
        'payment_id': payload['payment_id'],
        'order_id': payload['order_id'],
        'status': payload['status'],
        'amount': payload['amount'],
        'settled': payload['status'] == 'completed'
    }
    
    return {
        'status': 'success',
        'action': 'payment_processed',
        'processed_data': payment_data
    }

@app.route('/webhook', methods=['POST'])
def webhook_handler() -> Response:
    """
    Основной эндпоинт для обработки вебхуков
    CWE-470 mitigation: используем whitelist действий вместо динамического выполнения
    """
    # Валидация Content-Type
    if not request.is_json:
        return jsonify({
            'status': 'error',
            'message': 'Content-Type должен быть application/json'
        }), 400
    
    try:
        payload = request.get_json()
    except Exception as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        return jsonify({
            'status': 'error',
            'message': 'Неверный формат JSON'
        }), 400
    
    # Валидация обязательного поля 'action'
    if not payload or 'action' not in payload:
        return jsonify({
            'status': 'error',
            'message': 'Поле "action" обязательно'
        }), 400
    
    action = payload['action']
    
    # Проверка по whitelist (CWE-470 mitigation)
    if action not in ALLOWED_ACTIONS:
        logger.warning(f"Попытка вызова неразрешенного действия: {action}")
        return jsonify({
            'status': 'error',
            'message': f'Действие "{action}" не разрешено',
            'allowed_actions': list(ALLOWED_ACTIONS)
        }), 403
    
    # Поиск обработчика
    handler = _action_handlers.get(action)
    if not handler:
        logger.error(f"Обработчик для действия '{action}' не зарегистрирован")
        return jsonify({
            'status': 'error',
            'message': f'Обработчик для действия "{action}" не найден'
        }), 501
    
    # Выполнение обработчика
    try:
        result = handler(payload)
        logger.info(f"Действие '{action}' успешно обработано")
        
        # Формирование ответа
        response_data = {
            'status': 'success',
            'action': action,
            'result': result
        }
        
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Ошибка обработки действия '{action}': {e}")
        return jsonify({
            'status': 'error',
            'action': action,
            'message': 'Внутренняя ошибка сервера'
        }), 500

@app.route('/health', methods=['GET'])
def health_check() -> Response:
    """Эндпоинт для проверки работоспособности"""
    return jsonify({
        'status': 'healthy',
        'allowed_actions': list(ALLOWED_ACTIONS),
        'registered_handlers': list(_action_handlers.keys())
    }), 200

if __name__ == '__main__':
    # В продакшене используйте production-сервер (gunicorn/uwsgi)
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False  # В продакшене всегда False
    )