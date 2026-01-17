from pathlib import Path
from typing import Set


class FileNotFoundInRegistryError(Exception):
    """
    Исключение выбрасывается, если файл отсутствует
    в реестре базы данных.
    """
    pass


class FileStorageSecurityError(Exception):
    """
    Исключение выбрасывается при попытке доступа
    за пределы разрешённой директории хранения.
    """
    pass


class FileRegistry:
    """
    Класс-обёртка над реестром файлов.

    Имитирует таблицу в базе данных, где хранятся
    допустимые для скачивания имена файлов.
    """

    def __init__(self, registered_files: Set[str]) -> None:
        self._registered_files: Set[str] = registered_files

    def is_registered(self, file_name: str) -> bool:
        """
        Проверяет, зарегистрирован ли файл в реестре.

        :param file_name: Имя файла
        :return: True, если файл зарегистрирован
        """
        return file_name in self._registered_files


class FileDownloadManager:
    """
    Сервис для безопасной загрузки файлов из локального хранилища.
    """

    def __init__(self, registry: FileRegistry, storage_dir: Path) -> None:
        self._registry: FileRegistry = registry
        self._storage_dir: Path = storage_dir.resolve()

    def download_file(self, raw_file_name: str) -> bytes:
        """
        Основной метод загрузки файла.

        1. Очищает ввод пользователя
        2. Проверяет наличие файла в реестре
        3. Безопасно собирает путь
        4. Читает файл из файловой системы

        :param raw_file_name: Имя файла, полученное от пользователя
        :return: Содержимое файла в байтах
        """
        sanitized_file_name: str = self._sanitize_file_name(raw_file_name)

        if not self._registry.is_registered(sanitized_file_name):
            raise FileNotFoundInRegistryError(
                f"Файл '{sanitized_file_name}' отсутствует в реестре"
            )

        safe_path: Path = self._build_safe_path(sanitized_file_name)

        return self._read_file(safe_path)

    def _sanitize_file_name(self, file_name: str) -> str:
        """
        Удаляет любые элементы навигации по каталогам
        и оставляет только имя файла.
        """
        return Path(file_name).name

    def _build_safe_path(self, file_name: str) -> Path:
        """
        Собирает абсолютный путь к файлу и проверяет,
        что он не выходит за пределы директории хранения.
        """
        resolved_path: Path = (self._storage_dir / file_name).resolve()

        if not resolved_path.is_relative_to(self._storage_dir):
            raise FileStorageSecurityError(
                "Попытка выхода за пределы директории хранения"
            )

        return resolved_path

    def _read_file(self, file_path: Path) -> bytes:
        """
        Считывает файл с диска.
        """
        if not file_path.exists():
            raise FileNotFoundError(
                f"Файл '{file_path.name}' не найден в директории хранения"
            )

        return file_path.read_bytes()


def main() -> None:
    """
    Точка входа приложения.
    """
    registry = FileRegistry(
        registered_files={
            "report.pdf",
            "data.csv",
            "manual.txt",
        }
    )

    storage_directory: Path = Path("./documents")

    download_manager = FileDownloadManager(
        registry=registry,
        storage_dir=storage_directory,
    )

    # Пример использования
    try:
        file_content: bytes = download_manager.download_file("report.pdf")
        print(f"Файл загружен, размер: {len(file_content)} байт")
    except Exception as error:
        print(f"Ошибка загрузки файла: {error}")


if __name__ == "__main__":
    main()
