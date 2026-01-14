import os
from flask import Flask, request, send_file, abort
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Конфигурация
DOCUMENTS_FOLDER = './documents'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'png'}

def validate_filename(filename):
    """Проверка безопасности имени файла"""
    if not filename:
        return False
    
    # Безопасное получение имени файла
    secured_name = secure_filename(filename)
    if secured_name != filename:
        return False
    
    # Проверка расширения файла
    if '.' not in filename:
        return False
    
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False
    
    return True

def get_file_path(filename):
    """Получение полного пути к файлу"""
    return os.path.join(DOCUMENTS_FOLDER, filename)

@app.route('/download', methods=['GET'])
def download_file():
    """
    Эндпоинт для скачивания файла
    Параметры:
        filename (str): имя файла для скачивания
    """
    # Получаем имя файла из параметров запроса
    filename = request.args.get('filename')
    
    # Проверяем наличие параметра
    if not filename:
        abort(400, description="Не указано имя файла")
    
    # Валидация имени файла
    if not validate_filename(filename):
        abort(400, description="Некорректное имя файла")
    
    # Формируем полный путь к файлу
    file_path = get_file_path(filename)
    
    # Проверяем существование файла
    if not os.path.exists(file_path):
        abort(404, description="Файл не найден")
    
    # Проверяем, что это файл, а не директория
    if not os.path.isfile(file_path):
        abort(400, description="Указанный путь не является файлом")
    
    try:
        # Отправляем файл как вложение
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        # Логируем ошибку и возвращаем 500
        app.logger.error(f"Ошибка при отправке файла {filename}: {str(e)}")
        abort(500, description="Внутренняя ошибка сервера")

if __name__ == '__main__':
    # Создаем папку для документов, если она не существует
    os.makedirs(DOCUMENTS_FOLDER, exist_ok=True)
    app.run(debug=True)