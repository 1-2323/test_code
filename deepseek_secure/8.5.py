import os
import hashlib
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from typing import Tuple, Optional

app = Flask(__name__)

# Конфигурация
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'zip'}
app.config['REQUIRE_HASH_CHECK'] = True  # Требовать ли проверку хеша

# Создаем папку для загрузок, если ее нет
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename: str) -> bool:
    """Проверяет разрешенное расширение файла."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def calculate_hash(file_path: str, hash_algorithm: str = 'sha256') -> str:
    """Вычисляет хеш файла."""
    hash_func = hashlib.new(hash_algorithm)
    
    with open(file_path, 'rb') as f:
        # Читаем файл блоками для эффективной обработки больших файлов
        for chunk in iter(lambda: f.read(4096), b''):
            hash_func.update(chunk)
    
    return hash_func.hexdigest()

def verify_file_integrity(file_path: str, expected_hash: Optional[str] = None, 
                          hash_algorithm: str = 'sha256') -> Tuple[bool, Optional[str]]:
    """Проверяет целостность файла по хешу."""
    if not expected_hash:
        return True, None
    
    actual_hash = calculate_hash(file_path, hash_algorithm)
    
    if actual_hash == expected_hash:
        return True, actual_hash
    else:
        return False, actual_hash

@app.route('/upload', methods=['POST'])
def upload_file():
    """Эндпоинт для загрузки файлов с проверкой целостности."""
    
    # Проверяем наличие файла в запросе
    if 'file' not in request.files:
        return jsonify({
            'success': False,
            'error': 'No file part in the request'
        }), 400
    
    file = request.files['file']
    
    # Проверяем, что файл был выбран
    if file.filename == '':
        return jsonify({
            'success': False,
            'error': 'No file selected'
        }), 400
    
    # Проверяем расширение файла
    if not allowed_file(file.filename):
        return jsonify({
            'success': False,
            'error': f'File type not allowed. Allowed types: {", ".join(app.config["ALLOWED_EXTENSIONS"])}'
        }), 400
    
    # Безопасное имя файла
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    # Проверяем, не существует ли уже файл с таким именем
    counter = 1
    name, ext = os.path.splitext(filename)
    while os.path.exists(file_path):
        filename = f"{name}_{counter}{ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        counter += 1
    
    try:
        # Сохраняем файл
        file.save(file_path)
        
        # Получаем ожидаемый хеш из запроса (если предоставлен)
        expected_hash = request.form.get('expected_hash')
        hash_algorithm = request.form.get('hash_algorithm', 'sha256')
        
        # Проверяем целостность файла
        integrity_check_passed = True
        actual_hash = None
        
        if app.config['REQUIRE_HASH_CHECK'] and expected_hash:
            integrity_check_passed, actual_hash = verify_file_integrity(
                file_path, expected_hash, hash_algorithm
            )
        
        # Если проверка целостности не пройдена - удаляем файл
        if not integrity_check_passed:
            os.remove(file_path)
            return jsonify({
                'success': False,
                'error': 'File integrity check failed',
                'expected_hash': expected_hash,
                'actual_hash': actual_hash
            }), 400
        
        # Если хеш не был предоставлен, но требуется проверка - вычисляем и возвращаем хеш
        if app.config['REQUIRE_HASH_CHECK'] and not expected_hash:
            actual_hash = calculate_hash(file_path, hash_algorithm)
        
        # Получаем информацию о файле
        file_size = os.path.getsize(file_path)
        
        return jsonify({
            'success': True,
            'message': 'File uploaded successfully',
            'filename': filename,
            'file_path': file_path,
            'file_size': file_size,
            'hash': actual_hash,
            'hash_algorithm': hash_algorithm if actual_hash else None,
            'integrity_check': integrity_check_passed
        }), 201
        
    except Exception as e:
        # В случае ошибки удаляем частично загруженный файл, если он существует
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return jsonify({
            'success': False,
            'error': f'Upload failed: {str(e)}'
        }), 500

@app.errorhandler(413)
def too_large(e):
    """Обработчик ошибки превышения размера файла."""
    return jsonify({
        'success': False,
        'error': 'File size exceeds maximum allowed size (16MB)'
    }), 413

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)