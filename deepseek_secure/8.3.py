import hashlib
import hmac
import json
import logging
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Header, Request, status
from pydantic import BaseModel, ValidationError

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Configuration Update Service")


class ConfigUpdate(BaseModel):
    """Модель для валидации конфигурационных данных."""
    version: str
    data: Dict[str, Any]
    timestamp: str


class ConfigManager:
    """Менеджер для работы с конфигурацией."""
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key.encode()
        
    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Верификация цифровой подписи HMAC-SHA256."""
        try:
            expected_signature = hmac.new(
                self.secret_key,
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Сравнение подписей с постоянным временем выполнения
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Ошибка при верификации подписи: {e}")
            return False
    
    def apply_configuration(self, config_data: ConfigUpdate) -> bool:
        """Применение конфигурации."""
        try:
            # Здесь должна быть логика применения конфигурации
            # Например, сохранение в файл, обновление БД и т.д.
            
            logger.info(f"Применена конфигурация версии {config_data.version}")
            logger.debug(f"Данные конфигурации: {config_data.data}")
            
            # Временная заглушка - в реальном приложении здесь должна быть
            # логика применения конфигурации
            # config_path = "config/app_config.json"
            # with open(config_path, 'w') as f:
            #     json.dump(config_data.dict(), f, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при применении конфигурации: {e}")
            return False


# Инициализация менеджера конфигурации
# В реальном приложении ключ должен храниться в безопасном месте
CONFIG_MANAGER = ConfigManager(
    secret_key="your-secret-key-here-change-in-production"
)


@app.post("/update", 
          status_code=status.HTTP_200_OK,
          summary="Применить обновление конфигурации",
          description="Принимает и применяет конфигурацию от внешнего источника с верификацией цифровой подписи")
async def update_configuration(
    request: Request,
    x_signature: Optional[str] = Header(None, description="Цифровая подпись HMAC-SHA256"),
    x_timestamp: Optional[str] = Header(None, description="Временная метка запроса")
):
    """
    Эндпоинт для приема обновлений конфигурации.
    
    Требуемые заголовки:
    - X-Signature: Цифровая подпись HMAC-SHA256 тела запроса
    - X-Timestamp: Временная метка для предотвращения replay-атак
    
    Тело запроса должно содержать JSON с полями:
    - version: версия конфигурации
    - data: данные конфигурации
    - timestamp: временная метка конфигурации
    """
    
    # Проверка наличия обязательных заголовков
    if not x_signature:
        logger.warning("Запрос без цифровой подписи")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Требуется цифровая подпись (X-Signature header)"
        )
    
    if not x_timestamp:
        logger.warning("Запрос без временной метки")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Требуется временная метка (X-Timestamp header)"
        )
    
    try:
        # Чтение тела запроса
        body_bytes = await request.body()
        
        # Верификация цифровой подписи
        if not CONFIG_MANAGER.verify_signature(body_bytes, x_signature):
            logger.warning(f"Неверная цифровая подпись для запроса от {request.client.host}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверная цифровая подпись"
            )
        
        # Проверка свежести запроса (защита от replay-атак)
        # В реальном приложении здесь должна быть логика проверки временной метки
        logger.debug(f"Запрос с временной меткой: {x_timestamp}")
        
        # Парсинг JSON
        config_json = json.loads(body_bytes.decode('utf-8'))
        
        # Валидация данных конфигурации
        config_update = ConfigUpdate(**config_json)
        
        # Применение конфигурации
        if CONFIG_MANAGER.apply_configuration(config_update):
            logger.info(f"Конфигурация версии {config_update.version} успешно применена")
            return {
                "status": "success",
                "message": f"Конфигурация версии {config_update.version} успешно применена",
                "applied_version": config_update.version
            }
        else:
            logger.error(f"Не удалось применить конфигурацию версии {config_update.version}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ошибка при применении конфигурации"
            )
            
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат JSON"
        )
        
    except ValidationError as e:
        logger.error(f"Ошибка валидации данных: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка валидации данных: {e.errors()}"
        )
        
    except HTTPException:
        # Пробрасываем уже созданные HTTPException
        raise
        
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )


@app.get("/health", 
         status_code=status.HTTP_200_OK,
         summary="Проверка здоровья сервиса")
async def health_check():
    """Эндпоинт для проверки работоспособности сервиса."""
    return {
        "status": "healthy",
        "service": "configuration-update"
    }


if __name__ == "__main__":
    import uvicorn
    
    # В реальном приложении параметры должны браться из конфигурации
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )