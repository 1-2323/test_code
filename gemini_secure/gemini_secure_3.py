import json
from functools import wraps
from typing import Any, Callable, Dict, Final
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status, Depends
from pydantic import BaseModel, Field, ConfigDict, ValidationError

# --- Схемы данных (Pydantic) ---

class AppSettingsSchema(BaseModel):
    """
    Схема валидации глобальных настроек.
    Конфигурация extra='forbid' гарантирует запрет на передачу незаявленных полей.
    """
    model_config = ConfigDict(extra='forbid')

    title: str = Field(..., min_length=1, max_length=100)
    api_rate_limit: int = Field(..., ge=0, le=10000)
    enable_registration: bool = Field(default=True)


# --- Безопасность и Декораторы ---

def admin_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Декоратор для проверки прав администратора.
    В реальной системе здесь будет извлечение и проверка JWT/Session.
    """
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Имитация извлечения данных о пользователе из запроса
        request: Request = kwargs.get("request")
        if not request:
            raise HTTPException(status_code=500, detail="Internal Server Error: Request context missing")
        
        user_role = request.headers.get("X-User-Role")
        if user_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Administrative privileges required."
            )
        return await func(*args, **kwargs)
    return wrapper


# --- Сервис управления конфигурацией ---

class GlobalSettingsService:
    """
    Сервис для управления жизненным циклом конфигурации приложения.
    Реализует атомарную запись и валидацию данных.
    """

    SETTINGS_FILE: Final[Path] = Path("global_config.json")

    def __init__(self) -> None:
        # Инициализация файла настроек по умолчанию, если он отсутствует
        if not self.SETTINGS_FILE.exists():
            self._save_to_storage({"title": "Default App", "api_rate_limit": 100, "enable_registration": True})

    def _save_to_storage(self, data: Dict[str, Any]) -> None:
        """Сохраняет данные в файловое хранилище в формате JSON."""
        try:
            with open(self.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            raise RuntimeError(f"Failed to persist settings: {str(e)}")

    def update_settings(self, new_settings: AppSettingsSchema) -> Dict[str, Any]:
        """
        Выполняет сохранение валидированных данных.
        Метод вызывается только после успешной проверки прав доступа.
        """
        settings_dict = new_settings.model_dump()
        self._save_to_storage(settings_dict)
        return settings_dict


# --- FastAPI Приложение ---

app = FastAPI(title="Global Configuration Service")
settings_service = GlobalSettingsService()

@app.put("/admin/settings", status_code=status.HTTP_200_OK)
@admin_required
async def update_global_config(
    request: Request,
    payload: AppSettingsSchema
) -> Dict[str, Any]:
    """
    Эндпоинт для обновления глобальных настроек.
    
    1. Автоматическая валидация через AppSettingsSchema (запрет лишних полей).
    2. Проверка прав через декоратор @admin_required.
    3. Сохранение данных через сервис.
    """
    try:
        updated_data = settings_service.update_settings(payload)
        return {"status": "success", "updated_settings": updated_data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while saving configuration: {str(e)}"
        )