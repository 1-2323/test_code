import os
import sys
from flask import Flask

def create_app():
    """Создание и конфигурирование Flask-приложения"""
    app = Flask(__name__)
    
    # Базовая конфигурация
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
    app.config['JSON_AS_ASCII'] = False
    
    # Простой маршрут для проверки
    @app.route('/health')
    def health_check():
        return {'status': 'healthy'}, 200
    
    return app

def is_production():
    """Определение, работает ли приложение в production-окружении"""
    # Проверка переменных окружения, характерных для production
    production_indicators = [
        os.environ.get('FLASK_ENV') == 'production',
        os.environ.get('ENVIRONMENT') == 'production',
        os.environ.get('PRODUCTION') == 'true',
        'heroku' in os.environ.get('DYNO', '').lower(),
        os.environ.get('PYTHON_ENV') == 'production'
    ]
    
    return any(production_indicators)

def configure_debug_settings(app):
    """Конфигурация debug-режима в зависимости от окружения"""
    if is_production():
        # PRODUCTION: отключаем debug и подробные ошибки
        app.debug = False
        app.config['PROPAGATE_EXCEPTIONS'] = True
        app.config['TRAP_HTTP_EXCEPTIONS'] = True
        
        # Отключаем подробный вывод ошибок
        @app.errorhandler(500)
        def internal_server_error(error):
            return {'error': 'Internal Server Error'}, 500
            
        @app.errorhandler(404)
        def not_found_error(error):
            return {'error': 'Not Found'}, 404
            
        print("Запуск в PRODUCTION режиме", file=sys.stderr)
        print("Debug режим: ВЫКЛЮЧЕН", file=sys.stderr)
        print("Подробные ошибки: ВЫКЛЮЧЕНЫ", file=sys.stderr)
        
    else:
        # DEVELOPMENT: включаем debug и подробные ошибки
        app.debug = True
        app.config['EXPLAIN_TEMPLATE_LOADING'] = True
        
        print("Запуск в DEVELOPMENT режиме", file=sys.stderr)
        print("Debug режим: ВКЛЮЧЕН", file=sys.stderr)
        print("Подробные ошибки: ВКЛЮЧЕНЫ", file=sys.stderr)

def main():
    """Основная функция запуска приложения"""
    try:
        # Создаем приложение
        app = create_app()
        
        # Конфигурируем debug-режим
        configure_debug_settings(app)
        
        # Получаем параметры хоста и порта из переменных окружения
        host = os.environ.get('HOST', '127.0.0.1')
        port = int(os.environ.get('PORT', 5000))
        
        # Проверяем, что в production не используем небезопасные значения
        if is_production():
            if host == '127.0.0.1' or host == 'localhost':
                host = '0.0.0.0'
                print(f"Автоматическое изменение хоста на {host} для production", file=sys.stderr)
        
        # Запуск приложения
        print(f"Запуск сервера на {host}:{port}", file=sys.stderr)
        app.run(
            host=host,
            port=port,
            # debug параметр управляется через app.debug
            # чтобы избежать CWE-489, не передаем debug=True в run() в production
            use_reloader=app.debug,  # reloader только в development
            threaded=True
        )
        
    except Exception as e:
        print(f"Ошибка запуска приложения: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()