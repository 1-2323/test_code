from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import uuid
import requests
import time
import hashlib
from redis import Redis
import json
import logging
from functools import wraps

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///llm_generation.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['RATE_LIMIT_PER_MINUTE'] = int(os.environ.get('RATE_LIMIT_PER_MINUTE', 10))
app.config['MAX_INPUT_LENGTH'] = int(os.environ.get('MAX_INPUT_LENGTH', 2000))
app.config['LLM_API_URL'] = os.environ.get('LLM_API_URL', 'https://api.openai.com/v1/chat/completions')
app.config['LLM_API_KEY'] = os.environ.get('LLM_API_KEY', 'your-api-key-here')
app.config['LLM_MODEL'] = os.environ.get('LLM_MODEL', 'gpt-3.5-turbo')
app.config['LLM_MAX_TOKENS'] = int(os.environ.get('LLM_MAX_TOKENS', 1000))
app.config['LLM_TEMPERATURE'] = float(os.environ.get('LLM_TEMPERATURE', 0.7))

# Инициализация Redis для кэширования и rate limiting
redis_client = Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))

db = SQLAlchemy(app)

# Модель для хранения запросов к LLM
class GenerationRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)  # ID пользователя из системы аутентификации
    input_text = db.Column(db.Text, nullable=False)
    prompt_template = db.Column(db.Text, nullable=False)
    full_prompt = db.Column(db.Text)
    model = db.Column(db.String(100))
    generated_text = db.Column(db.Text)
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed
    tokens_used = db.Column(db.Integer)
    processing_time_ms = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    
    # Для кэширования
    input_hash = db.Column(db.String(64), index=True)
    response_hash = db.Column(db.String(64), index=True)

# Модель для промпт-шаблонов
class PromptTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    template = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    system_prompt = db.Column(db.Text)
    max_tokens = db.Column(db.Integer, default=500)
    temperature = db.Column(db.Float, default=0.7)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def rate_limit(f):
    """
    Декоратор для ограничения частоты запросов
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # В реальном приложении используйте user_id из аутентификации
        # user_id = get_current_user_id()
        # key = f"rate_limit:{user_id}"
        
        # Временно используем IP-адрес
        ip = request.remote_addr
        key = f"rate_limit:{ip}"
        
        # Проверяем количество запросов за последнюю минуту
        current = redis_client.get(key)
        if current:
            current = int(current)
            if current >= app.config['RATE_LIMIT_PER_MINUTE']:
                return jsonify({
                    'success': False,
                    'error': 'Rate limit exceeded. Please try again later.'
                }), 429
        else:
            current = 0
        
        # Увеличиваем счетчик
        redis_client.incr(key)
        redis_client.expire(key, 60)  # Сбрасываем через 60 секунд
        
        return f(*args, **kwargs)
    return decorated_function

def cache_response(input_hash, response_data, ttl_seconds=3600):
    """
    Кэширование ответа LLM
    """
    cache_key = f"llm_cache:{input_hash}"
    redis_client.setex(cache_key, ttl_seconds, json.dumps(response_data))

def get_cached_response(input_hash):
    """
    Получение кэшированного ответа
    """
    cache_key = f"llm_cache:{input_hash}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    return None

@app.route('/generate', methods=['POST'])
@rate_limit
def generate_text():
    """
    Эндпоинт для генерации текста с использованием LLM
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())
    
    try:
        # В реальном приложении здесь должна быть аутентификация
        # user_id = get_current_user_id()
        user_id = 1
        
        data = request.get_json()
        
        # Валидация входных данных
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        input_text = data.get('text')
        template_name = data.get('template', 'default')
        parameters = data.get('parameters', {})
        
        if not input_text or not isinstance(input_text, str):
            return jsonify({
                'success': False,
                'error': 'Text input is required and must be a string'
            }), 400
        
        # Проверка длины ввода
        if len(input_text) > app.config['MAX_INPUT_LENGTH']:
            return jsonify({
                'success': False,
                'error': f'Input text too long. Maximum {app.config["MAX_INPUT_LENGTH"]} characters.'
            }), 400
        
        # Получение промпт-шаблона
        template = PromptTemplate.query.filter_by(name=template_name, is_active=True).first()
        if not template:
            return jsonify({
                'success': False,
                'error': f'Template "{template_name}" not found or inactive'
            }), 404
        
        # Формирование полного промпта
        try:
            full_prompt = template.template.format(text=input_text, **parameters)
        except KeyError as e:
            return jsonify({
                'success': False,
                'error': f'Missing parameter in template: {str(e)}'
            }), 400
        
        # Проверка длины промпта
        if len(full_prompt) > 4000:  # Ограничение для большинства LLM API
            return jsonify({
                'success': False,
                'error': 'Generated prompt is too long'
            }), 400
        
        # Создание хеша для кэширования
        input_hash = hashlib.sha256(full_prompt.encode()).hexdigest()
        
        # Проверка кэша
        cached_response = get_cached_response(input_hash)
        if cached_response:
            logger.info(f"Cache hit for request {request_id}")
            
            # Создаем запись в базе о кэшированном ответе
            generation_request = GenerationRequest(
                request_id=request_id,
                user_id=user_id,
                input_text=input_text[:500],  # Сохраняем только часть для экономии места
                prompt_template=template.template[:500],
                full_prompt=full_prompt[:500],
                model=app.config['LLM_MODEL'],
                generated_text=cached_response['generated_text'],
                status='completed',
                tokens_used=cached_response['tokens_used'],
                processing_time_ms=int((time.time() - start_time) * 1000),
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string,
                input_hash=input_hash,
                response_hash=hashlib.sha256(cached_response['generated_text'].encode()).hexdigest()
            )
            
            db.session.add(generation_request)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'request_id': request_id,
                'generated_text': cached_response['generated_text'],
                'cached': True,
                'tokens_used': cached_response['tokens_used'],
                'processing_time_ms': int((time.time() - start_time) * 1000),
                'model': app.config['LLM_MODEL'],
                'template': template_name
            }), 200
        
        # Если нет в кэше, создаем запись о запросе
        generation_request = GenerationRequest(
            request_id=request_id,
            user_id=user_id,
            input_text=input_text[:500],
            prompt_template=template.template[:500],
            full_prompt=full_prompt[:500],
            model=app.config['LLM_MODEL'],
            status='processing',
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string,
            input_hash=input_hash
        )
        
        db.session.add(generation_request)
        db.session.commit()
        
        # Вызов внешнего LLM API
        try:
            llm_response = call_llm_api(full_prompt, template)
            
            if not llm_response or 'generated_text' not in llm_response:
                raise Exception('Invalid response from LLM API')
            
            # Обновляем запись о запросе
            generation_request.generated_text = llm_response['generated_text']
            generation_request.status = 'completed'
            generation_request.tokens_used = llm_response.get('tokens_used', 0)
            generation_request.processing_time_ms = int((time.time() - start_time) * 1000)
            generation_request.response_hash = hashlib.sha256(llm_response['generated_text'].encode()).hexdigest()
            
            # Кэшируем ответ
            cache_response(input_hash, {
                'generated_text': llm_response['generated_text'],
                'tokens_used': llm_response.get('tokens_used', 0)
            }, ttl_seconds=86400)  # Кэшируем на 24 часа
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'request_id': request_id,
                'generated_text': llm_response['generated_text'],
                'cached': False,
                'tokens_used': llm_response.get('tokens_used', 0),
                'processing_time_ms': int((time.time() - start_time) * 1000),
                'model': app.config['LLM_MODEL'],
                'template': template_name
            }), 200
            
        except Exception as e:
            logger.error(f"LLM API error: {str(e)}")
            
            generation_request.status = 'failed'
            db.session.commit()
            
            return jsonify({
                'success': False,
                'error': 'Failed to generate text',
                'request_id': request_id
            }), 500
            
    except Exception as e:
        logger.error(f"Error in generate_text: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

def call_llm_api(prompt, template):
    """
    Вызов внешнего LLM API
    """
    headers = {
        'Authorization': f'Bearer {app.config["LLM_API_KEY"]}',
        'Content-Type': 'application/json'
    }
    
    # Формируем системный промпт
    system_prompt = template.system_prompt if template.system_prompt else "You are a helpful AI assistant."
    
    # Формируем сообщения для chat-based API (например, OpenAI)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    payload = {
        "model": app.config['LLM_MODEL'],
        "messages": messages,
        "max_tokens": template.max_tokens or app.config['LLM_MAX_TOKENS'],
        "temperature": template.temperature or app.config['LLM_TEMPERATURE'],
        "top_p": 1.0,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0
    }
    
    try:
        response = requests.post(
            app.config['LLM_API_URL'],
            headers=headers,
            json=payload,
            timeout=30  # Таймаут 30 секунд
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Извлекаем сгенерированный текст из ответа
            generated_text = data['choices'][0]['message']['content'].strip()
            
            # Получаем информацию об использованных токенах
            tokens_used = data.get('usage', {}).get('total_tokens', 0)
            
            return {
                'generated_text': generated_text,
                'tokens_used': tokens_used
            }
        else:
            logger.error(f"LLM API error: {response.status_code} - {response.text}")
            raise Exception(f"LLM API returned status code {response.status_code}")
            
    except requests.exceptions.Timeout:
        logger.error("LLM API request timeout")
        raise Exception("LLM API request timeout")
    except requests.exceptions.RequestException as e:
        logger.error(f"LLM API request failed: {str(e)}")
        raise Exception(f"LLM API request failed: {str(e)}")

# Эндпоинт для управления шаблонами
@app.route('/templates', methods=['GET'])
def list_templates():
    """
    Получение списка доступных шаблонов
    """
    try:
        templates = PromptTemplate.query.filter_by(is_active=True).all()
        
        templates_list = []
        for template in templates:
            templates_list.append({
                'name': template.name,
                'description': template.description,
                'max_tokens': template.max_tokens,
                'temperature': template.temperature,
                'created_at': template.created_at.isoformat()
            })
        
        return jsonify({
            'success': True,
            'templates': templates_list
        }), 200
        
    except Exception as e:
        logger.error(f"Error in list_templates: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Эндпоинт для получения информации о запросе
@app.route('/generate/<request_id>', methods=['GET'])
def get_generation_status(request_id):
    """
    Получение статуса и результата генерации
    """
    try:
        generation_request = GenerationRequest.query.filter_by(request_id=request_id).first()
        
        if not generation_request:
            return jsonify({
                'success': False,
                'error': 'Request not found'
            }), 404
        
        response_data = {
            'request_id': generation_request.request_id,
            'status': generation_request.status,
            'created_at': generation_request.created_at.isoformat(),
            'processing_time_ms': generation_request.processing_time_ms,
            'model': generation_request.model,
            'tokens_used': generation_request.tokens_used
        }
        
        if generation_request.status == 'completed':
            response_data['generated_text'] = generation_request.generated_text
            response_data['cached'] = generation_request.input_hash is not None
        
        return jsonify({
            'success': True,
            'data': response_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error in get_generation_status: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Инициализация базы данных
def init_db():
    with app.app_context():
        db.create_all()
        # Создаем дефолтный шаблон если база пуста
        if not PromptTemplate.query.first():
            default_template = PromptTemplate(
                name='default',
                template='Please process the following text:\n\n{text}\n\nProvide a helpful response.',
                description='Default template for text processing',
                system_prompt='You are a helpful AI assistant that processes user input.',
                max_tokens=500,
                temperature=0.7
            )
            db.session.add(default_template)
            
            # Пример другого шаблона
            summary_template = PromptTemplate(
                name='summarize',
                template='Summarize the following text:\n\n{text}\n\nSummary:',
                description='Template for text summarization',
                system_prompt='You are an AI assistant that specializes in creating concise summaries.',
                max_tokens=300,
                temperature=0.5
            )
            db.session.add(summary_template)
            
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5000)