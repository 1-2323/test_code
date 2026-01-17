import os
from pathlib import Path
from typing import Final, Set


class FileServiceError(Exception):
    """Базовый класс для исключений сервиса."""
    pass


class AccessDeniedError(FileServiceError):
    """Исключение при попытке доступа к запрещенным директориям."""
    pass


class ResourceNotFoundError(FileServiceError):
    """Исключение, если файл не найден в реестре или на диске."""
    pass


class FileDownloadManager:
    """
    Менеджер для безопасной загрузки файлов из локального хранилища.
    Обеспечивает защиту от Path Traversal и валидацию через реестр БД.
    """

    # Константа базовой директории, приведенная к абсолютному пути
    STORAGE_ROOT: Final[Path] = Path("./documents/").resolve()

    def __init__(self) -> None:
        """
        Инициализация менеджера. 
        В реальном приложении здесь должна быть инициализация клиента БД.
        """
        # Имитация реестра разрешенных файлов в БД
        self._allowed_files_registry: Set[str] = {
            "report.pdf",
            "invoice.docx",
            "data.json"
        }

    def _get_validated_path(self, filename: str) -> Path:
        """
        Очищает ввод и проверяет, что путь находится внутри STORAGE_ROOT.
        
        :param filename: Имя файла или путь, переданный пользователем.
        :return: Валидированный объект Path.
        :raises AccessDeniedError: Если путь ведет за пределы хранилища.
        """
        # Извлекаем только имя файла, отсекая любые попытки указать путь (напр. ../../)
        basename: str = os.path.basename(filename)
        
        # Строим абсолютный путь к целевому файлу
        target_path: Path = (self.STORAGE_ROOT / basename).resolve()

        # Проверка: начинается ли итоговый путь с пути нашей корневой папки
        if not str(target_path).startswith(str(self.STORAGE_ROOT)):
            raise AccessDeniedError(f"Security violation: path traversal detected for {filename}")

        return target_path

    def get_file_content(self, filename: str) -> bytes:
        """
        Возвращает содержимое файла после прохождения проверок безопасности и БД.

        :param filename: Запрашиваемое имя файла.
        :return: Содержимое файла в байтах.
        :raises ResourceNotFoundError: Если файл не зарегистрирован или отсутствует.
        """
        # 1. Проверка наличия записи в реестре БД
        if filename not in self._allowed_files_registry:
            raise ResourceNotFoundError(f"File '{filename}' is not registered in the database.")

        # 2. Получение безопасного пути к файлу
        safe_path: Path = self._get_validated_path(filename)

        # 3. Проверка физического существования файла на диске
        if not safe_path.is_file():
            raise ResourceNotFoundError(f"File '{filename}' exists in DB but is missing in storage.")

        # 4. Чтение данных
        try:
            return safe_path.read_bytes()
        except IOError as e:
            # Обработка ошибок ввода-вывода при чтении
            raise FileServiceError(f"Failed to read file '{filename}': {str(e)}")