import os
from flask import Flask, send_file, request, abort
from werkzeug.security import safe_join

app = Flask(__name__)
BASE_DIRECTORY = "./documents/"

@app.route('/download', methods=['GET'])
def download_file():
    filename = request.args.get('filename')
    
    if not filename:
        abort(400, description="Filename parameter is required")
    
    try:
        # Безопасное объединение путей, предотвращает выход за пределы BASE_DIRECTORY
        safe_path = safe_join(BASE_DIRECTORY, filename)
        
        if safe_path is None:
            abort(400, description="Invalid filename")
        
        # Проверяем, что путь находится внутри целевой директории
        if not os.path.abspath(safe_path).startswith(os.path.abspath(BASE_DIRECTORY)):
            abort(403, description="Access denied")
        
        # Проверяем существование файла
        if not os.path.exists(safe_path):
            abort(404, description="File not found")
        
        # Проверяем, что это файл, а не директория
        if not os.path.isfile(safe_path):
            abort(400, description="Requested path is not a file")
        
        # Отправляем файл как вложение
        return send_file(
            safe_path,
            as_attachment=True,
            download_name=os.path.basename(filename)
        )
        
    except (ValueError, TypeError) as e:
        abort(400, description="Invalid file path")
    except Exception as e:
        # Логирование ошибки для отладки
        app.logger.error(f"Error downloading file: {str(e)}")
        abort(500, description="Internal server error")

if __name__ == '__main__':
    # Создаем директорию documents если она не существует
    os.makedirs(BASE_DIRECTORY, exist_ok=True)
    app.run(debug=True)