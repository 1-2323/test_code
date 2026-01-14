from flask import Flask, request, jsonify
from functools import wraps
import json
import logging
from typing import Dict, Any, Callable, Optional

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Реестр обработчиков действий
_action_handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def register_action(action_type: str):
    """Декоратор для регистрации обработчиков действий"""
    def decorator(handler: Callable[[Dict[str, Any]], Dict[str, Any]]):
        _action_handlers[action_type] = handler
        return handler
    return decorator


def verify_signature(secret_token: str, payload: bytes, signature: Optional[str]) -> bool:
    """Валидация подписи вебхука (заглушка для реализации)"""
    if not secret_token or not signature:
        return True  # В реальном приложении здесь должна быть настоящая проверка
    
    # TODO: Реализовать проверку подписи в соответствии с документацией сервиса
    # Пример для GitHub: HMAC hexdigest сравнение
    return True


def webhook_auth(f):
    """Декоратор для аутентификации вебхука"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        secret_token = app.config.get('WEBHOOK_SECRET')
        signature = request.headers.get('X-Hub-Signature-256') or request.headers.get('X-Signature')
        
        if not verify_signature(secret_token, request.data, signature):
            logger.warning("Неверная подпись вебхука")
            return jsonify({'error': 'Invalid signature'}), 401
        
        return f(*args, **kwargs)
    return decorated_function


# Примеры обработчиков действий
@register_action('user_created')
def handle_user_created(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик создания пользователя"""
    user_data = payload.get('user', {})
    logger.info(f"Обработка создания пользователя: {user_data.get('email')}")
    
    # Логика обработки
    # TODO: Добавить бизнес-логику
    
    return {
        'status': 'processed',
        'action': 'user_created',
        'user_id': user_data.get('id'),
        'message': 'User created successfully'
    }


@register_action('order_updated')
def handle_order_updated(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик обновления заказа"""
    order_data = payload.get('order', {})
    logger.info(f"Обработка обновления заказа: {order_data.get('id')}")
    
    # Логика обработки
    # TODO: Добавить бизнес-логику
    
    return {
        'status': 'processed',
        'action': 'order_updated',
        'order_id': order_data.get('id'),
        'changes': payload.get('changes', {})
    }


@register_action('payment_received')
def handle_payment_received(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик получения платежа"""
    payment_data = payload.get('payment', {})
    logger.info(f"Обработка платежа: {payment_data.get('transaction_id')}")
    
    # Логика обработки
    # TODO: Добавить бизнес-логику
    
    return {
        'status': 'processed',
        'action': 'payment_received',
        'transaction_id': payment_data.get('transaction_id'),
        'amount': payment_data.get('amount')
    }


def process_webhook_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Основная функция обработки payload вебхука"""
    try:
        # Определение типа действия
        action_type = payload.get('action')
        event_type = payload.get('event')
        
        # Поддержка разных форматов payload
        action_key = action_type or event_type
        
        if not action_key:
            logger.error("Payload не содержит информацию о действии")
            return {
                'status': 'error',
                'message': 'No action specified in payload'
            }
        
        # Поиск обработчика
        handler = _action_handlers.get(action_key)
        
        if not handler:
            logger.warning(f"Нет обработчика для действия: {action_key}")
            return {
                'status': 'ignored',
                'action': action_key,
                'message': f'No handler for action: {action_key}'
            }
        
        # Выполнение обработчика
        result = handler(payload)
        logger.info(f"Действие '{action_key}' успешно обработано")
        
        return {
            'status': 'success',
            'processed_action': action_key,
            'result': result
        }
        
    except Exception as e:
        logger.error(f"Ошибка обработки payload: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'message': f'Processing error: {str(e)}'
        }


@app.route('/webhook', methods=['POST'])
@webhook_auth
def webhook_endpoint():
    """Основной эндпоинт для обработки вебхуков"""
    try:
        # Определение формата данных
        content_type = request.content_type or ''
        
        if 'application/json' in content_type:
            payload = request.get_json()
        elif 'application/x-www-form-urlencoded' in content_type:
            payload = request.form.to_dict()
        elif 'text/plain' in content_type:
            payload = json.loads(request.data.decode('utf-8'))
        else:
            # Попытка автоматического определения
            try:
                payload = request.get_json(force=True, silent=True) or json.loads(request.data.decode('utf-8'))
            except:
                payload = request.form.to_dict()
        
        if not payload:
            logger.error("Пустой или нечитаемый payload")
            return jsonify({
                'status': 'error',
                'message': 'Empty or unreadable payload'
            }), 400
        
        # Логирование входящего вебхука
        logger.info(f"Получен вебхук. Content-Type: {content_type}")
        logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
        
        # Обработка payload
        result = process_webhook_payload(payload)
        
        # Формирование ответа
        status_code = 200 if result['status'] in ['success', 'processed', 'ignored'] else 400
        
        return jsonify(result), status_code
        
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Invalid JSON format'
        }), 400
        
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Internal server error'
        }), 500


def register_custom_handler(action_type: str, handler_func: Callable[[Dict[str, Any]], Dict[str, Any]]):
    """Функция для динамической регистрации обработчиков"""
    _action_handlers[action_type] = handler_func
    logger.info(f"Зарегистрирован обработчик для действия: {action_type}")


# Конфигурация приложения (пример)
app.config.update(
    WEBHOOK_SECRET='your-secret-token-here',  # Замените на реальный секрет
    JSONIFY_PRETTYPRINT_REGULAR=True,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024  # Ограничение размера payload: 16MB
)


if __name__ == '__main__':
    # В реальном приложении используйте production WSGI сервер
    app.run(host='0.0.0.0', port=5000, debug=False)