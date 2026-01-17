import json
from functools import wraps
from pathlib import Path
from typing import Callable, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, Field


# =========================
# Константы и пути
# =========================

SETTINGS_STORAGE_PATH: Path = Path("./global_settings.json")


# =========================
# Pydantic-модели
# =========================

class User(BaseModel):
    """
    Модель пользователя,
    получаемого из сессии.
    """
    id: int
    username: str
    is_admin: bool


class ApiRates(BaseModel):
    """
    Модель лимитов API.
    """
    requests_per_minute: int = Field(..., gt=0)
    requests_per_day: int = Field(..., gt=0)


class GlobalSettings(BaseModel):
    """
    Модель глобальных настроек системы.
    """
    title: str
    api_rates: ApiRates


# =========================
# Хранилище настроек
# =========================

class GlobalSettingsRepository:
    """
    Репозиторий для сохранения и загрузки глобальных настроек.
    Работает с файловым хранилищем (JSON).
    """

    def __init__(self, storage_path: Path) -> None:
        self._storage_path: Path = storage_path

    def load(self) -> Dict[str, Any]:
        """
        Загружает настройки из файла.
        Если файл отсутствует — возвращает пустой словарь.
        """
        if not self._storage_path.exists():
            return {}

        with self._storage_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def save(self, settings: GlobalSettings) -> None:
        """
        Сохраняет настройки в файл.
        """
        with self._storage_path.open("w", encoding="utf-8") as file:
            json.dump(settings.dict(), file, ensure_ascii=False, indent=4)


# =========================
# Сервис
# =========================

class GlobalSettingsService:
    """
    Сервис управления глобальными настройками.
    """

    def __init__(self, repository: GlobalSettingsRepository) -> None:
        self._repository: GlobalSettingsRepository = repository

    def update_settings(self, settings: GlobalSettings) -> GlobalSettings:
        """
        Обновляет глобальные настройки и сохраняет их.
        """
        self._repository.save(settings)
        return settings


# =========================
# Авторизация и доступ
# =========================

def get_current_user() -> User:
    """
    Имитация получения текущего пользователя из сессии.
    """
    return User(
        id=1,
        username="admin",
        is_admin=True,
    )


def admin_required(func: Callable) -> Callable:
    """
    Декоратор для проверки прав администратора.
    Используется для эндпоинтов изменения конфигурации.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        current_user: User = kwargs.get("current_user")

        if current_user is None or not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges required",
            )

        return func(*args, **kwargs)

    return wrapper


# =========================
# Dependencies
# =========================

def get_settings_repository() -> GlobalSettingsRepository:
    """
    Dependency для репозитория настроек.
    """
    return GlobalSettingsRepository(storage_path=SETTINGS_STORAGE_PATH)


def get_settings_service(
    repository: GlobalSettingsRepository = Depends(get_settings_repository),
) -> GlobalSettingsService:
    """
    Dependency для сервиса настроек.
    """
    return GlobalSettingsService(repository=repository)


# =========================
# FastAPI-приложение
# =========================

app = FastAPI(title="Global Settings Service")


@app.put("/settings", response_model=GlobalSettings)
@admin_required
def update_global_settings(
    settings: GlobalSettings,
    current_user: User = Depends(get_current_user),
    service: GlobalSettingsService = Depends(get_settings_service),
) -> GlobalSettings:
    """
    Эндпоинт обновления глобальных JSON-настроек.

    Алгоритм:
    1. Проверка прав администратора (декоратор)
    2. Валидация входных данных через Pydantic
    3. Сохранение настроек в хранилище
    4. Возврат обновлённой конфигурации
    """
    return service.update_settings(settings)
