import json
from functools import wraps
from pathlib import Path
from typing import Dict, Callable, Any

from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict


# =========================
# МОДЕЛИ ПОЛЬЗОВАТЕЛЯ
# =========================

class User(BaseModel):
    """
    Модель пользователя системы.
    """
    id: int
    username: str
    is_admin: bool


def get_current_user() -> User:
    """
    Имитирует получение текущего пользователя из сессии.
    """
    return User(
        id=1,
        username="admin_user",
        is_admin=True,
    )


# =========================
# ДЕКОРАТОР ПРОВЕРКИ ПРАВ
# =========================

def require_admin_permissions(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Декоратор, проверяющий наличие прав администратора
    перед выполнением бизнес-логики.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        current_user: User = kwargs.get("current_user")

        if current_user is None or not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для изменения глобальных настроек",
            )

        return func(*args, **kwargs)

    return wrapper


# =========================
# Pydantic-СХЕМЫ
# =========================

class ApiRatesSettings(BaseModel):
    """
    Схема API-лимитов.
    """
    requests_per_minute: int = Field(gt=0)
    burst_limit: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class GlobalSettingsUpdateRequest(BaseModel):
    """
    Схема обновления глобальных настроек.
    """
    title: str = Field(min_length=3, max_length=100)
    api_rates: ApiRatesSettings

    model_config = ConfigDict(extra="forbid")


class GlobalSettingsResponse(BaseModel):
    """
    Схема ответа с текущими настройками.
    """
    title: str
    api_rates: Dict[str, int]


# =========================
# СЕРВИС НАСТРОЕК
# =========================

class GlobalSettingsService:
    """
    Сервис управления глобальными настройками приложения.
    """

    def __init__(self, storage_path: Path) -> None:
        self._storage_path: Path = storage_path
        self._ensure_storage_exists()

    def _ensure_storage_exists(self) -> None:
        """
        Создаёт файл настроек, если он отсутствует.
        """
        if not self._storage_path.exists():
            default_settings = {
                "title": "Default Application",
                "api_rates": {
                    "requests_per_minute": 60,
                    "burst_limit": 10,
                },
            }
            self._write_to_storage(default_settings)

    def load_settings(self) -> Dict[str, Any]:
        """
        Загружает настройки из файла.
        """
        with self._storage_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def update_settings(
        self,
        settings: GlobalSettingsUpdateRequest,
        current_user: User,
    ) -> GlobalSettingsResponse:
        """
        Обновляет настройки после проверки прав доступа.
        """
        self._check_permissions(current_user)

        updated_data: Dict[str, Any] = settings.model_dump()

        self._write_to_storage(updated_data)

        return GlobalSettingsResponse(
            title=updated_data["title"],
            api_rates=updated_data["api_rates"],
        )

    def _check_permissions(self, user: User) -> None:
        """
        Проверяет права доступа пользователя.
        """
        if not user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Пользователь не имеет прав администратора",
            )

    def _write_to_storage(self, data: Dict[str, Any]) -> None:
        """
        Сохраняет настройки в файл.
        """
        with self._storage_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)


# =========================
# FASTAPI ПРИЛОЖЕНИЕ
# =========================

app = FastAPI(
    title="Global Settings Service",
    version="1.0.0",
    description="Сервис управления глобальными настройками",
)

settings_storage_path = Path("./global_settings.json")
settings_service = GlobalSettingsService(settings_storage_path)


# =========================
# ENDPOINT
# =========================

@app.put(
    "/settings",
    response_model=GlobalSettingsResponse,
    summary="Обновить глобальные настройки",
)
@require_admin_permissions
def update_global_settings(
    settings: GlobalSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> GlobalSettingsResponse:
    """
    Эндпоинт обновления глобальных JSON-настроек.

    Проверка прав доступа выполняется
    непосредственно перед сохранением данных.
    """
    return settings_service.update_settings(
        settings=settings,
        current_user=current_user,
    )
