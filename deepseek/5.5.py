#!/usr/bin/env python3
"""
Скрипт запуска Flask-приложения с настройками отладки и подробным выводом ошибок.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import traceback
import json
from datetime import datetime

# Добавляем путь к проекту в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, request, jsonify, render_template_string, Response
from werkzeug.exceptions import HTTPException, InternalServerError
from werkzeug.serving import WSGIRequestHandler
import click


class DebugConfig:
    """Конфигурация режима отладки"""
    
    def __init__(
        self,
        debug: bool = True,
        host: str = "127.0.0.1",
        port: int = 5000,
        reload: bool = True,
        reloader_type: str = "stat",  # "stat", "watchdog", or "poll"
        use_debugger: bool = True,
        use_reloader: bool = True,
        threaded: bool = True,
        processes: int = 1,
        ssl_context: Optional[tuple] = None,
        extra_files: Optional[List[str]] = None,
        expose_host: bool = False,
        log_level: str = "DEBUG",
        enable_profiler: bool = False,
        profiler_output_dir: str = "profiler",
    ):
        self.debug = debug
        self.host = host if not expose_host else "0.0.0.0"
        self.port = port
        self.reload = reload
        self.reloader_type = reloader_type
        self.use_debugger = use_debugger
        self.use_reloader = use_reloader
        self.threaded = threaded
        self.processes = processes
        self.ssl_context = ssl_context
        self.extra_files = extra_files or []
        self.expose_host = expose_host
        self.log_level = log_level
        self.enable_profiler = enable_profiler
        self.profiler_output_dir = profiler_output_dir
        
        # Устанавливаем переменные окружения для Flask
        if debug:
            os.environ['FLASK_ENV'] = 'development'
            os.environ['FLASK_DEBUG'] = '1'
        else:
            os.environ['FLASK_ENV'] = 'production'
            os.environ['FLASK_DEBUG'] = '0'


class DetailedErrorHandler:
    """Обработчик ошибок с подробным выводом"""
    
    def __init__(self, app: Flask, debug_mode: bool = True):
        self.app = app
        self.debug_mode = debug_mode
        self.setup_error_handlers()
    
    def setup_error_handlers(self):
        """Настройка обработчиков ошибок"""
        
        @self.app.errorhandler(HTTPException)
        def handle_http_exception(error: HTTPException):
            """Обработчик HTTP исключений"""
            return self._create_error_response(
                error=error,
                status_code=error.code,
                error_type=error.__class__.__name__,
                description=error.description,
                is_http_exception=True
            )
        
        @self.app.errorhandler(Exception)
        def handle_general_exception(error: Exception):
            """Обработчик всех остальных исключений"""
            return self._create_error_response(
                error=error,
                status_code=500,
                error_type=error.__class__.__name__,
                description="Internal Server Error",
                is_http_exception=False
            )
        
        # Переопределяем встроенный обработчик ошибок Flask
        self.app.config['TRAP_HTTP_EXCEPTIONS'] = True
        self.app.config['PROPAGATE_EXCEPTIONS'] = True
        
        # Middleware для логирования всех ошибок
        @self.app.after_request
        def log_errors(response: Response):
            """Логирование ошибок после обработки запроса"""
            if 400 <= response.status_code < 600:
                self._log_error_response(request, response)
            return response
    
    def _create_error_response(self, error, status_code, error_type, description, is_http_exception):
        """Создание подробного ответа с ошибкой"""
        
        # Собираем информацию об ошибке
        error_info = {
            "success": False,
            "error": {
                "code": status_code,
                "type": error_type,
                "message": str(description),
                "timestamp": datetime.utcnow().isoformat(),
                "path": request.path if request else None,
                "method": request.method if request else None,
            }
        }
        
        # Добавляем traceback в режиме отладки
        if self.debug_mode and not is_http_exception:
            error_info["error"]["traceback"] = traceback.format_exception(
                type(error), error, error.__traceback__
            )
            
            # Добавляем дополнительную информацию об исключении
            error_info["error"]["exception_args"] = getattr(error, 'args', None)
            error_info["error"]["exception_module"] = error.__class__.__module__
        
        # Добавляем информацию о запросе
        if request:
            error_info["error"]["request"] = {
                "url": request.url,
                "headers": dict(request.headers),
                "args": dict(request.args),
                "form": dict(request.form),
                "json": request.get_json(silent=True),
                "endpoint": request.endpoint,
                "blueprint": request.blueprint,
                "remote_addr": request.remote_addr,
                "user_agent": str(request.user_agent),
            }
        
        # Определяем формат ответа
        accept_header = request.headers.get('Accept', '') if request else ''
        
        if 'text/html' in accept_header and self.debug_mode:
            # HTML ответ для браузера в режиме отладки
            return self._create_html_error_response(error_info, status_code)
        else:
            # JSON ответ по умолчанию
            response = jsonify(error_info)
            response.status_code = status_code
            return response
    
    def _create_html_error_response(self, error_info: Dict[str, Any], status_code: int) -> str:
        """Создание HTML страницы с подробной информацией об ошибке"""
        
        html_template = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Error {{ error.code }} - {{ error.type }}</title>
            <style>
                body {
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    background-color: #f5f5f5;
                    color: #333;
                    margin: 0;
                    padding: 20px;
                }
                .error-container {
                    max-width: 1200px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    overflow: hidden;
                }
                .error-header {
                    background: #dc3545;
                    color: white;
                    padding: 20px;
                }
                .error-header h1 {
                    margin: 0;
                    font-size: 24px;
                }
                .error-body {
                    padding: 20px;
                }
                .error-section {
                    margin-bottom: 25px;
                    border-bottom: 1px solid #eee;
                    padding-bottom: 15px;
                }
                .error-section:last-child {
                    border-bottom: none;
                }
                .section-title {
                    color: #dc3545;
                    font-weight: bold;
                    margin-bottom: 10px;
                    font-size: 18px;
                }
                .traceback {
                    background: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    padding: 15px;
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    font-size: 12px;
                    white-space: pre-wrap;
                    overflow-x: auto;
                    max-height: 400px;
                    overflow-y: auto;
                }
                .request-info {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 15px;
                }
                .info-box {
                    background: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    padding: 15px;
                }
                .info-box h4 {
                    margin-top: 0;
                    color: #495057;
                    border-bottom: 1px solid #dee2e6;
                    padding-bottom: 5px;
                }
                .code-block {
                    background: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    padding: 10px;
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    font-size: 12px;
                    overflow-x: auto;
                }
                pre {
                    margin: 0;
                }
                .json-key {
                    color: #d73a49;
                }
                .json-string {
                    color: #032f62;
                }
                .json-number {
                    color: #005cc5;
                }
                .json-boolean {
                    color: #6f42c1;
                }
                .json-null {
                    color: #6a737d;
                }
            </style>
        </head>
        <body>
            <div class="error-container">
                <div class="error-header">
                    <h1>Error {{ error.code }}: {{ error.type }}</h1>
                    <p>{{ error.message }}</p>
                    <p><small>{{ error.timestamp }}</small></p>
                </div>
                
                <div class="error-body">
                    {% if error.traceback %}
                    <div class="error-section">
                        <div class="section-title">Traceback</div>
                        <div class="traceback">{{ error.traceback | join('\n') }}</div>
                    </div>
                    {% endif %}
                    
                    {% if error.request %}
                    <div class="error-section">
                        <div class="section-title">Request Information</div>
                        <div class="request-info">
                            <div class="info-box">
                                <h4>Basic Info</h4>
                                <p><strong>URL:</strong> {{ error.request.url }}</p>
                                <p><strong>Method:</strong> {{ error.request.method }}</p>
                                <p><strong>Endpoint:</strong> {{ error.request.endpoint or 'N/A' }}</p>
                                <p><strong>Blueprint:</strong> {{ error.request.blueprint or 'N/A' }}</p>
                                <p><strong>Remote Address:</strong> {{ error.request.remote_addr }}</p>
                            </div>
                            
                            {% if error.request.args %}
                            <div class="info-box">
                                <h4>Query Parameters</h4>
                                <div class="code-block">
                                    <pre>{{ error.request.args | tojson(indent=2) }}</pre>
                                </div>
                            </div>
                            {% endif %}
                            
                            {% if error.request.form %}
                            <div class="info-box">
                                <h4>Form Data</h4>
                                <div class="code-block">
                                    <pre>{{ error.request.form | tojson(indent=2) }}</pre>
                                </div>
                            </div>
                            {% endif %}
                            
                            {% if error.request.json %}
                            <div class="info-box">
                                <h4>JSON Body</h4>
                                <div class="code-block">
                                    <pre>{{ error.request.json | tojson(indent=2) }}</pre>
                                </div>
                            </div>
                            {% endif %}
                            
                            <div class="info-box">
                                <h4>Headers</h4>
                                <div class="code-block">
                                    <pre>{{ error.request.headers | tojson(indent=2) }}</pre>
                                </div>
                            </div>
                            
                            <div class="info-box">
                                <h4>User Agent</h4>
                                <div class="code-block">
                                    <pre>{{ error.request.user_agent }}</pre>
                                </div>
                            </div>
                        </div>
                    </div>
                    {% endif %}
                    
                    {% if error.exception_args %}
                    <div class="error-section">
                        <div class="section-title">Exception Arguments</div>
                        <div class="code-block">
                            <pre>{{ error.exception_args | tojson(indent=2) }}</pre>
                        </div>
                    </div>
                    {% endif %}
                    
                    <div class="error-section">
                        <div class="section-title">Full Error Response (JSON)</div>
                        <div class="code-block">
                            <pre>{{ error_info | tojson(indent=2) }}</pre>
                        </div>
                    </div>
                </div>
            </div>
            
            <script>
            // Подсветка JSON
            function syntaxHighlight(json) {
                if (typeof json != 'string') {
                    json = JSON.stringify(json, null, 2);
                }
                json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                return json.replace(
                    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
                    function (match) {
                        let cls = 'json-number';
                        if (/^"/.test(match)) {
                            if (/:$/.test(match)) {
                                cls = 'json-key';
                            } else {
                                cls = 'json-string';
                            }
                        } else if (/true|false/.test(match)) {
                            cls = 'json-boolean';
                        } else if (/null/.test(match)) {
                            cls = 'json-null';
                        }
                        return '<span class="' + cls + '">' + match + '</span>';
                    }
                );
            }
            
            // Применяем подсветку ко всем pre элементам с JSON
            document.querySelectorAll('pre').forEach(pre => {
                try {
                    const json = JSON.parse(pre.textContent);
                    pre.innerHTML = syntaxHighlight(json);
                } catch (e) {
                    // Не JSON, оставляем как есть
                }
            });
            </script>
        </body>
        </html>
        """
        
        return render_template_string(html_template, error_info=error_info, error=error_info['error']), status_code
    
    def _log_error_response(self, request, response):
        """Логирование ошибки"""
        logger = logging.getLogger('flask.error')
        logger.error(
            f"{response.status_code} {request.method} {request.path}",
            extra={
                'status_code': response.status_code,
                'method': request.method,
                'path': request.path,
                'ip': request.remote_addr,
                'user_agent': request.user_agent.string,
                'headers': dict(request.headers),
                'args': dict(request.args),
                'form': dict(request.form),
                'json': request.get_json(silent=True),
            }
        )


class DebugRequestHandler(WSGIRequestHandler):
    """Кастомный обработчик запросов с подробным логированием"""
    
    def log(self, type, message, *args):
        """Переопределение логирования запросов"""
        if type == 'error':
            # Подробное логирование ошибок
            logger = logging.getLogger('werkzeug.error')
            logger.error(f"{self.address_string()} - {message % args}")
        else:
            # Стандартное логирование
            super().log(type, message, *args)
    
    def log_request(self, code='-', size='-'):
        """Логирование деталей запроса"""
        if code >= 400:
            # Детальное логирование для ошибок
            logger = logging.getLogger('werkzeug.request')
            logger.warning(
                f'"{self.requestline}" {code} {size}',
                extra={
                    'client_ip': self.address_string(),
                    'method': self.command,
                    'path': self.path,
                    'protocol': self.request_version,
                    'status': code,
                    'size': size,
                    'headers': dict(self.headers),
                }
            )
        else:
            # Стандартное логирование для успешных запросов
            super().log_request(code, size)


class FlaskDebugRunner:
    """Запуск Flask приложения с поддержкой отладки"""
    
    def __init__(self, app: Flask, config: Optional[DebugConfig] = None):
        self.app = app
        self.config = config or DebugConfig()
        self._setup_logging()
        self._setup_app()
    
    def _setup_logging(self):
        """Настройка подробного логирования"""
        
        log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
        
        # Настройка root логгера
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format=log_format,
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('flask_debug.log', encoding='utf-8')
            ]
        )
        
        # Настройка логгера Werkzeug (HTTP запросы)
        werkzeug_logger = logging.getLogger('werkzeug')
        werkzeug_logger.setLevel(logging.INFO)
        
        # Настройка логгера Flask
        flask_logger = logging.getLogger('flask')
        flask_logger.setLevel(logging.DEBUG)
        
        # Отключаем стандартный логгер Werkzeug для использования нашего
        if not self.config.debug:
            werkzeug_logger.disabled = True
    
    def _setup_app(self):
        """Настройка Flask приложения для отладки"""
        
        # Конфигурация приложения
        self.app.config.update(
            DEBUG=self.config.debug,
            ENV='development' if self.config.debug else 'production',
            SECRET_KEY=os.urandom(24),
            SESSION_COOKIE_SECURE=False,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16 MB
            JSON_SORT_KEYS=False,
            JSONIFY_PRETTYPRINT_REGULAR=self.config.debug,
            EXPLAIN_TEMPLATE_LOADING=self.config.debug,
            TEMPLATES_AUTO_RELOAD=self.config.debug,
        )
        
        # Добавляем обработчик ошибок с подробным выводом
        if self.config.debug:
            self.error_handler = DetailedErrorHandler(self.app, debug_mode=True)
        
        # Добавляем endpoint для информации о дебаге
        @self.app.route('/debug/info')
        def debug_info():
            """Endpoint для получения информации о режиме отладки"""
            if not self.config.debug:
                return jsonify({"error": "Debug mode is disabled"}), 403
            
            info = {
                "debug": self.app.debug,
                "environment": self.app.env,
                "config": {
                    k: str(v) for k, v in self.app.config.items()
                    if not k.startswith('SECRET') and not k.startswith('PASSWORD')
                },
                "endpoints": sorted([rule.rule for rule in self.app.url_map.iter_rules()]),
                "python": {
                    "version": sys.version,
                    "executable": sys.executable,
                    "path": sys.path,
                },
                "process": {
                    "pid": os.getpid(),
                    "cwd": os.getcwd(),
                    "user": os.getenv('USER'),
                },
                "server": {
                    "host": self.config.host,
                    "port": self.config.port,
                    "threaded": self.config.threaded,
                    "processes": self.config.processes,
                }
            }
            return jsonify(info)
        
        # Добавляем endpoint для проверки ошибок
        @self.app.route('/debug/error-test')
        def error_test():
            """Endpoint для тестирования обработки ошибок"""
            if not self.config.debug:
                return jsonify({"error": "Debug mode is disabled"}), 403
            
            # Генерируем различные типы ошибок
            error_type = request.args.get('type', 'value')
            
            if error_type == 'value':
                raise ValueError("Тестовая ошибка ValueError")
            elif error_type == 'key':
                raise KeyError("Тестовая ошибка KeyError")
            elif error_type == 'index':
                raise IndexError("Тестовая ошибка IndexError")
            elif error_type == 'attribute':
                raise AttributeError("Тестовая ошибка AttributeError")
            elif error_type == 'type':
                raise TypeError("Тестовая ошибка TypeError")
            elif error_type == 'zero':
                return 1 / 0
            elif error_type == 'import':
                import nonexistent_module
            elif error_type == 'json':
                return jsonify({"error": "Test"}), 400
            else:
                raise Exception("Общая тестовая ошибка")
        
        # Добавляем endpoint для просмотра логов
        @self.app.route('/debug/logs')
        def view_logs():
            """Endpoint для просмотра логов в реальном времени"""
            if not self.config.debug:
                return jsonify({"error": "Debug mode is disabled"}), 403
            
            log_file = request.args.get('file', 'flask_debug.log')
            lines = int(request.args.get('lines', 100))
            
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    log_lines = f.readlines()[-lines:]
                return render_template_string('''
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Logs: {{ log_file }}</title>
                        <style>
                            body { font-family: monospace; white-space: pre; }
                            .error { color: red; }
                            .warning { color: orange; }
                            .info { color: blue; }
                            .debug { color: gray; }
                        </style>
                    </head>
                    <body>
                        {% for line in logs %}
                            {% if 'ERROR' in line %}
                                <div class="error">{{ line }}</div>
                            {% elif 'WARNING' in line %}
                                <div class="warning">{{ line }}</div>
                            {% elif 'INFO' in line %}
                                <div class="info">{{ line }}</div>
                            {% elif 'DEBUG' in line %}
                                <div class="debug">{{ line }}</div>
                            {% else %}
                                <div>{{ line }}</div>
                            {% endif %}
                        {% endfor %}
                    </body>
                    </html>
                ''', logs=log_lines, log_file=log_file)
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        # Middleware для логирования всех запросов
        @self.app.before_request
        def log_request():
            """Логирование входящих запросов"""
            if self.config.debug:
                logger = logging.getLogger('flask.request')
                logger.debug(
                    f"Incoming request: {request.method} {request.path}",
                    extra={
                        'method': request.method,
                        'path': request.path,
                        'ip': request.remote_addr,
                        'user_agent': request.user_agent.string,
                        'headers': dict(request.headers),
                        'args': dict(request.args),
                    }
                )
        
        @self.app.after_request
        def log_response(response):
            """Логирование исходящих ответов"""
            if self.config.debug:
                logger = logging.getLogger('flask.response')
                logger.debug(
                    f"Outgoing response: {response.status}",
                    extra={
                        'status': response.status,
                        'content_type': response.content_type,
                        'content_length': response.content_length,
                    }
                )
            return response
    
    def run(self):
        """Запуск Flask приложения с настройками отладки"""
        
        print("\n" + "="*60)
        print("FLASK DEBUG SERVER STARTING")
        print("="*60)
        
        # Выводим информацию о конфигурации
        print(f"\n📝 Конфигурация:")
        print(f"  • Host: {self.config.host}")
        print(f"  • Port: {self.config.port}")
        print(f"  • Debug: {self.config.debug}")
        print(f"  • Reload: {self.config.use_reloader}")
        print(f"  • Threaded: {self.config.threaded}")
        print(f"  • Log Level: {self.config.log_level}")
        
        print(f"\n🌐 Доступные endpoints:")
        print(f"  • http://{self.config.host}:{self.config.port}/ - Основное приложение")
        print(f"  • http://{self.config.host}:{self.config.port}/debug/info - Информация о дебаге")
        print(f"  • http://{self.config.host}:{self.config.port}/debug/error-test - Тест ошибок")
        print(f"  • http://{self.config.host}:{self.config.port}/debug/logs - Просмотр логов")
        
        print(f"\n⚙️  Параметры запуска:")
        print(f"  • PID: {os.getpid()}")
        print(f"  • Python: {sys.version.split()[0]}")
        print(f"  • Flask: {self._get_flask_version()}")
        print(f"  • Рабочая директория: {os.getcwd()}")
        
        print(f"\n📁 Логи:")
        print(f"  • Консоль: Включено (уровень: {self.config.log_level})")
        print(f"  • Файл: flask_debug.log")
        
        print(f"\n🚀 Запуск сервера...")
        print("="*60 + "\n")
        
        try:
            # Запуск приложения с настройками
            self.app.run(
                host=self.config.host,
                port=self.config.port,
                debug=self.config.debug,
                use_debugger=self.config.use_debugger,
                use_reloader=self.config.use_reloader,
                reloader_type=self.config.reloader_type,
                threaded=self.config.threaded,
                processes=self.config.processes,
                ssl_context=self.config.ssl_context,
                extra_files=self.config.extra_files,
                request_handler=DebugRequestHandler if self.config.debug else None,
            )
        except KeyboardInterrupt:
            print("\n\n👋 Сервер остановлен пользователем")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Ошибка запуска сервера: {str(e)}")
            traceback.print_exc()
            sys.exit(1)
    
    def _get_flask_version(self):
        """Получение версии Flask"""
        try:
            import flask
            return flask.__version__
        except:
            return "Unknown"


# CLI команды с использованием Click
@click.group()
def cli():
    """CLI для запуска Flask приложения с отладкой"""
    pass


@cli.command()
@click.option('--host', default='127.0.0.1', help='Хост для запуска сервера')
@click.option('--port', default=5000, help='Порт для запуска сервера')
@click.option('--debug/--no-debug', default=True, help='Режим отладки')
@click.option('--reload/--no-reload', default=True, help='Автоперезагрузка при изменениях')
@click.option('--expose', is_flag=True, help='Разрешить доступ с других хостов')
@click.option('--log-level', default='DEBUG', 
              type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']),
              help='Уровень логирования')
@click.option('--ssl', is_flag=True, help='Включить SSL')
@click.option('--ssl-key', type=click.Path(exists=True), help='Путь к SSL ключу')
@click.option('--ssl-cert', type=click.Path(exists=True), help='Путь к SSL сертификату')
def run(host, port, debug, reload, expose, log_level, ssl, ssl_key, ssl_cert):
    """Запустить Flask приложение с настройками отладки"""
    
    # Конфигурация SSL
    ssl_context = None
    if ssl:
        if ssl_key and ssl_cert:
            ssl_context = (ssl_cert, ssl_key)
        else:
            click.echo("⚠️  SSL requires both --ssl-key and --ssl-cert options")
            ssl_context = 'adhoc'  # Самоподписанный сертификат для разработки
    
    # Создаем конфигурацию
    config = DebugConfig(
        debug=debug,
        host=host,
        port=port,
        use_reloader=reload,
        expose_host=expose,
        log_level=log_level,
        ssl_context=ssl_context,
    )
    
    # Ищем Flask приложение
    app = find_flask_app()
    
    if app is None:
        click.echo("❌ Не удалось найти Flask приложение")
        click.echo("Создайте файл app.py или укажите переменную окружения FLASK_APP")
        sys.exit(1)
    
    # Запускаем приложение
    runner = FlaskDebugRunner(app, config)
    runner.run()


@cli.command()
def info():
    """Показать информацию о текущем Flask приложении"""
    
    app = find_flask_app()
    
    if app is None:
        click.echo("❌ Flask приложение не найдено")
        return
    
    click.echo("\n📊 Информация о Flask приложении:")
    click.echo(f"  • Название: {app.name}")
    click.echo(f"  • Режим: {'Разработка' if app.debug else 'Продакшен'}")
    click.echo(f"  • Путь: {app.root_path}")
    
    click.echo("\n📋 Зарегистрированные endpoints:")
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint != 'static':
            click.echo(f"  • {rule.rule} [{', '.join(rule.methods - {'OPTIONS', 'HEAD'})}]")
    
    click.echo("\n⚙️  Конфигурация:")
    for key, value in sorted(app.config.items()):
        if not key.startswith('SECRET_') and not key.startswith('PASSWORD_'):
            click.echo(f"  • {key}: {value}")


@cli.command()
@click.option('--lines', default=50, help='Количество строк для вывода')
def logs(lines):
    """Показать последние логи приложения"""
    
    log_file = 'flask_debug.log'
    
    if not os.path.exists(log_file):
        click.echo(f"❌ Файл логов '{log_file}' не найден")
        return
    
    with open(log_file, 'r', encoding='utf-8') as f:
        log_lines = f.readlines()[-lines:]
    
    click.echo(f"\n📄 Последние {lines} строк логов из {log_file}:")
    click.echo("="*80)
    
    for line in log_lines:
        line = line.rstrip()
        if 'ERROR' in line:
            click.secho(line, fg='red')
        elif 'WARNING' in line:
            click.secho(line, fg='yellow')
        elif 'INFO' in line:
            click.secho(line, fg='blue')
        elif 'DEBUG' in line:
            click.secho(line, fg='green')
        else:
            click.echo(line)


def find_flask_app():
    """
    Поиск Flask приложения в текущем проекте.
    Поддерживает различные способы указания приложения.
    """
    
    # Проверяем переменную окружения FLASK_APP
    flask_app_env = os.getenv('FLASK_APP')
    
    if flask_app_env:
        # Формат: "path.to:app"
        if ':' in flask_app_env:
            module_name, app_name = flask_app_env.split(':', 1)
        else:
            module_name, app_name = flask_app_env, 'app'
        
        try:
            module = __import__(module_name, fromlist=[app_name])
            app = getattr(module, app_name)
            
            if isinstance(app, Flask):
                return app
        except ImportError as e:
            print(f"Ошибка импорта {flask_app_env}: {str(e)}")
    
    # Пробуем найти приложение в текущей директории
    possible_app_files = [
        'app.py',
        'application.py',
        'main.py',
        'wsgi.py',
        'run.py',
    ]
    
    for app_file in possible_app_files:
        if os.path.exists(app_file):
            try:
                # Динамически импортируем модуль
                import importlib.util
                
                spec = importlib.util.spec_from_file_location("flask_app", app_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Ищем Flask приложение в модуле
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, Flask):
                        return attr
            except Exception as e:
                print(f"Ошибка загрузки {app_file}: {str(e)}")
                continue
    
    return None


# Фабрика для создания тестового приложения
def create_example_app() -> Flask:
    """Создание тестового Flask приложения для демонстрации"""
    
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        return '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Flask Debug Server</title>
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
                .header { background: #4CAF50; color: white; padding: 20px; border-radius: 8px; }
                .content { margin-top: 20px; }
                .card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
                .card h3 { margin-top: 0; }
                .btn { display: inline-block; background: #4CAF50; color: white; padding: 10px 20px; 
                       text-decoration: none; border-radius: 4px; margin-right: 10px; }
                .btn-error { background: #f44336; }
                .btn-warning { background: #ff9800; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🚀 Flask Debug Server</h1>
                <p>Сервер запущен в режиме отладки с подробным выводом ошибок</p>
            </div>
            
            <div class="content">
                <div class="card">
                    <h3>Тестирование возможностей</h3>
                    <p>Попробуйте следующие endpoints:</p>
                    <p>
                        <a href="/debug/info" class="btn">Информация о дебаге</a>
                        <a href="/debug/logs" class="btn">Просмотр логов</a>
                    </p>
                    <p>Тест ошибок:</p>
                    <p>
                        <a href="/debug/error-test?type=value" class="btn btn-error">ValueError</a>
                        <a href="/debug/error-test?type=zero" class="btn btn-error">ZeroDivision</a>
                        <a href="/debug/error-test?type=key" class="btn btn-warning">KeyError</a>
                        <a href="/debug/error-test?type=index" class="btn btn-warning">IndexError</a>
                    </p>
                </div>
                
                <div class="card">
                    <h3>Пример API endpoints</h3>
                    <p>
                        <a href="/api/users" class="btn">Список пользователей</a>
                        <a href="/api/data" class="btn">Получить данные</a>
                    </p>
               