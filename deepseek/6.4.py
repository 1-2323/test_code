import os
import uuid
from typing import Dict, Any, Tuple
from pathlib import Path

from flask import request, jsonify, current_app
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps, UnidentifiedImageError
import magic

# Константы для конфигурации аватаров
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
AVATAR_SIZES = {
    'large': (400, 400),
    'medium': (200, 200),
    'small': (80, 80),
    'thumbnail': (40, 40)
}
ALLOWED_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp'
}


class AvatarProcessingError(Exception):
    """Базовое исключение для ошибок обработки аватара."""
    pass


class FileValidationError(AvatarProcessingError):
    """Исключение для ошибок валидации файла."""
    pass


class ImageProcessingError(AvatarProcessingError):
    """Исключение для ошибок обработки изображения."""
    pass


class AvatarProcessor:
    """Класс для обработки и валидации аватаров пользователей."""
    
    def __init__(self, upload_folder: str, base_url: str = '/static/avatars/'):
        """
        Инициализация процессора аватаров.
        
        Args:
            upload_folder: Папка для сохранения аватаров
            base_url: Базовый URL для доступа к аватарам
        """
        self.upload_folder = Path(upload_folder)
        self.base_url = base_url
        self._ensure_upload_dirs()
    
    def _ensure_upload_dirs(self) -> None:
        """Создает необходимые директории для сохранения аватаров."""
        # Создаем основную директорию
        self.upload_folder.mkdir(parents=True, exist_ok=True)
        
        # Создаем поддиректории для каждого размера
        for size_name in AVATAR_SIZES.keys():
            size_dir = self.upload_folder / size_name
            size_dir.mkdir(exist_ok=True)
    
    def validate_file(self, file_storage) -> Tuple[str, str]:
        """
        Валидирует загруженный файл.
        
        Args:
            file_storage: Файл из request.files
            
        Returns:
            Кортеж (расширение файла, MIME-тип)
            
        Raises:
            FileValidationError: Если файл не прошел валидацию
        """
        # Проверка наличия файла
        if not file_storage or file_storage.filename == '':
            raise FileValidationError('Файл не был загружен')
        
        # Проверка имени файла
        filename = secure_filename(file_storage.filename)
        if not filename:
            raise FileValidationError('Некорректное имя файла')
        
        # Проверка расширения файла
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        if file_ext not in ALLOWED_EXTENSIONS:
            raise FileValidationError(
                f'Недопустимое расширение файла. Разрешены: {", ".join(ALLOWED_EXTENSIONS)}'
            )
        
        # Проверка размера файла
        file_storage.seek(0, os.SEEK_END)
        file_size = file_storage.tell()
        file_storage.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            raise FileValidationError(
                f'Размер файла превышает максимальный ({MAX_FILE_SIZE // 1024 // 1024}MB)'
            )
        
        # Проверка MIME-типа через magic
        mime = magic.Magic(mime=True)
        mime_type = mime.from_buffer(file_storage.read(1024))
        file_storage.seek(0)
        
        if mime_type not in ALLOWED_MIME_TYPES:
            raise FileValidationError(
                f'Недопустимый тип файла. Разрешены: {", ".join(ALLOWED_MIME_TYPES)}'
            )
        
        # Дополнительная проверка: расширение должно соответствовать MIME-типу
        expected_extensions = {
            'image/jpeg': {'jpg', 'jpeg'},
            'image/png': {'png'},
            'image/gif': {'gif'},
            'image/webp': {'webp'}
        }
        
        if mime_type in expected_extensions and file_ext not in expected_extensions[mime_type]:
            raise FileValidationError('Расширение файла не соответствует его содержимому')
        
        return file_ext, mime_type
    
    def process_and_save_avatar(self, file_storage, user_id: int) -> Dict[str, str]:
        """
        Обрабатывает и сохраняет аватар пользователя.
        
        Args:
            file_storage: Загруженный файл
            user_id: ID пользователя
            
        Returns:
            Словарь с URL аватаров разных размеров
            
        Raises:
            ImageProcessingError: Если не удалось обработать изображение
        """
        try:
            # Генерируем уникальное имя файла
            unique_filename = f"{user_id}_{uuid.uuid4().hex}"
            
            # Открываем изображение
            image = Image.open(file_storage)
            
            # Конвертируем в RGB если необходимо
            if image.mode in ('RGBA', 'LA', 'P'):
                # Создаем белый фон для прозрачных изображений
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Автоматически поворачиваем изображение на основе EXIF данных
            image = ImageOps.exif_transpose(image)
            
            # Сохраняем оригинал (временный файл)
            original_path = self.upload_folder / f"{unique_filename}_original.jpg"
            image.save(original_path, 'JPEG', quality=95, optimize=True)
            
            # Создаем и сохраняем версии разных размеров
            avatar_urls = {}
            
            for size_name, dimensions in AVATAR_SIZES.items():
                # Создаем копию изображения
                resized_image = image.copy()
                
                # Изменяем размер с сохранением пропорций
                resized_image.thumbnail(dimensions, Image.Resampling.LANCZOS)
                
                # Создаем квадратное изображение
                squared_image = Image.new('RGB', dimensions, (240, 240, 240))
                
                # Вставляем изображение по центру
                offset = (
                    (dimensions[0] - resized_image.size[0]) // 2,
                    (dimensions[1] - resized_image.size[1]) // 2
                )
                squared_image.paste(resized_image, offset)
                
                # Сохраняем
                size_filename = f"{unique_filename}_{size_name}.jpg"
                size_path = self.upload_folder / size_name / size_filename
                squared_image.save(size_path, 'JPEG', quality=85, optimize=True)
                
                # Формируем URL
                avatar_urls[size_name] = f"{self.base_url}{size_name}/{size_filename}"
            
            # Удаляем временный оригинал
            original_path.unlink()
            
            # Закрываем изображение
            image.close()
            
            return avatar_urls
            
        except UnidentifiedImageError:
            raise ImageProcessingError('Невозможно открыть изображение. Файл поврежден или имеет неверный формат')
        except Exception as e:
            raise ImageProcessingError(f'Ошибка обработки изображения: {str(e)}')
    
    def delete_old_avatars(self, user_id: int) -> None:
        """
        Удаляет старые аватары пользователя.
        
        Args:
            user_id: ID пользователя
        """
        try:
            for size_dir in self.upload_folder.iterdir():
                if size_dir.is_dir():
                    for file_path in size_dir.glob(f"{user_id}_*.jpg"):
                        try:
                            file_path.unlink()
                        except OSError:
                            pass
        except Exception:
            # Игнорируем ошибки удаления старых файлов
            pass


def create_avatar_endpoint():
    """
    Создает эндпоинт для загрузки аватара пользователя.
    
    Возвращает функцию-обработчик для Flask роута.
    """
    
    # Инициализация процессора аватаров
    upload_folder = current_app.config.get('AVATAR_UPLOAD_FOLDER', './static/avatars')
    avatar_base_url = current_app.config.get('AVATAR_BASE_URL', '/static/avatars/')
    
    avatar_processor = AvatarProcessor(upload_folder, avatar_base_url)
    
    def upload_avatar():
        """
        Эндпоинт POST /profile/avatar
        Загружает и обрабатывает аватар пользователя.
        """
        # Получаем пользователя из контекста (предполагается аутентификация)
        # В реальном приложении здесь будет current_user или аналогичный объект
        user_id = get_current_user_id()  # Эта функция должна быть реализована в вашем приложении
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'Требуется аутентификация'
            }), 401
        
        # Проверяем наличие файла в запросе
        if 'avatar' not in request.files:
            return jsonify({
                'success': False,
                'error': 'Файл с ключом "avatar" не найден в запросе'
            }), 400
        
        file_storage = request.files['avatar']
        
        try:
            # Валидация файла
            file_ext, mime_type = avatar_processor.validate_file(file_storage)
            
            # Удаляем старые аватары пользователя
            avatar_processor.delete_old_avatars(user_id)
            
            # Обрабатываем и сохраняем новый аватар
            avatar_urls = avatar_processor.process_and_save_avatar(file_storage, user_id)
            
            # Сохраняем информацию о аватаре в базе данных
            save_avatar_to_database(user_id, avatar_urls)  # Эта функция должна быть реализована в вашем приложении
            
            # Логируем успешную загрузку
            current_app.logger.info(
                f'Аватар успешно загружен для пользователя {user_id}. '
                f'Тип: {mime_type}, размеры: {list(AVATAR_SIZES.keys())}'
            )
            
            # Возвращаем успешный ответ
            return jsonify({
                'success': True,
                'message': 'Аватар успешно загружен',
                'avatar_urls': avatar_urls,
                'user_id': user_id
            }), 200
            
        except FileValidationError as e:
            current_app.logger.warning(f'Ошибка валидации файла для пользователя {user_id}: {str(e)}')
            return jsonify({
                'success': False,
                'error': str(e),
                'details': 'file_validation_error'
            }), 400
            
        except ImageProcessingError as e:
            current_app.logger.error(f'Ошибка обработки изображения для пользователя {user_id}: {str(e)}')
            return jsonify({
                'success': False,
                'error': str(e),
                'details': 'image_processing_error'
            }), 500
            
        except Exception as e:
            current_app.logger.error(f'Неожиданная ошибка при загрузке аватара для пользователя {user_id}: {str(e)}')
            return jsonify({
                'success': False,
                'error': 'Внутренняя ошибка сервера',
                'details': 'server_error'
            }), 500
    
    return upload_avatar


# Вспомогательные функции (должны быть реализованы в вашем приложении)
def get_current_user_id() -> int:
    """
    Получает ID текущего аутентифицированного пользователя.
    В реальном приложении эта функция будет получать пользователя из контекста.
    
    Returns:
        ID пользователя или None если пользователь не аутентифицирован
    """
    # Пример реализации с Flask-Login:
    # from flask_login import current_user
    # return current_user.id if current_user.is_authenticated else None
    
    # Заглушка для примера:
    return 1


def save_avatar_to_database(user_id: int, avatar_urls: Dict[str, str]) -> None:
    """
    Сохраняет информацию об аватаре в базе данных.
    
    Args:
        user_id: ID пользователя
        avatar_urls: Словарь с URL аватаров разных размеров
    """
    # Пример реализации с SQLAlchemy:
    # user = User.query.get(user_id)
    # user.avatar_url = avatar_urls.get('medium')
    # user.avatar_urls = json.dumps(avatar_urls)
    # db.session.commit()
    
    # В реальном приложении здесь будет код сохранения в БД
    pass


# Пример регистрации эндпоинта в Flask приложении
def register_avatar_endpoint(app):
    """
    Регистрирует эндпоинт для загрузки аватара в Flask приложении.
    
    Args:
        app: Flask приложение
    """
    # Настройка конфигурации
    app.config['AVATAR_UPLOAD_FOLDER'] = './static/avatars'
    app.config['AVATAR_BASE_URL'] = '/static/avatars/'
    app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
    
    # Создание директории для загрузок если её нет
    upload_folder = app.config['AVATAR_UPLOAD_FOLDER']
    Path(upload_folder).mkdir(parents=True, exist_ok=True)
    
    # Регистрация эндпоинта
    app.add_url_rule(
        '/profile/avatar',
        'upload_avatar',
        create_avatar_endpoint(),
        methods=['POST']
    )
    
    # Добавление middleware для ограничения размера файла
    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({
            'success': False,
            'error': f'Размер файла превышает максимальный ({MAX_FILE_SIZE // 1024 // 1024}MB)'
        }), 413


# Пример использования в Flask приложении:
"""
from flask import Flask
import logging

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Регистрация эндпоинта
register_avatar_endpoint(app)

if __name__ == '__main__':
    app.run(debug=True)
"""