from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Dict, Optional
from datetime import datetime
import uuid
import json
import os

app = FastAPI(title="Тестирование API", version="1.0.0")

# Модели данных
class TestSubmission(BaseModel):
    user_id: str = Field(..., min_length=1, description="ID пользователя")
    test_id: str = Field(..., min_length=1, description="ID теста")
    score: float = Field(..., ge=0, le=100, description="Набранные баллы")

class CertificateResponse(BaseModel):
    certificate_id: str
    user_id: str
    test_id: str
    score: float
    passing_threshold: float
    passed: bool
    issue_date: str
    download_url: Optional[str] = None

# Зависимости и конфигурация
class TestConfig:
    def __init__(self):
        self.passing_thresholds = self._load_thresholds()
        self.certificates_dir = "./certificates"
        self._ensure_certificates_dir()
    
    def _load_thresholds(self) -> Dict[str, float]:
        """Загрузка пороговых значений из серверного хранилища"""
        # В реальном приложении здесь было бы подключение к БД или файлу конфигурации
        # Используем фиктивные данные для демонстрации
        return {
            "test_001": 70.0,
            "test_002": 80.0,
            "test_003": 65.0,
            "test_004": 75.0
        }
    
    def _ensure_certificates_dir(self):
        """Создание директории для сертификатов"""
        if not os.path.exists(self.certificates_dir):
            os.makedirs(self.certificates_dir)
    
    def get_passing_threshold(self, test_id: str) -> float:
        """Получение проходного порога для теста"""
        threshold = self.passing_thresholds.get(test_id)
        if threshold is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Тест с ID {test_id} не найден"
            )
        return threshold
    
    def save_certificate(self, certificate_data: dict) -> str:
        """Сохранение сертификата в файл"""
        certificate_id = str(uuid.uuid4())
        filename = f"{self.certificates_dir}/{certificate_id}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(certificate_data, f, ensure_ascii=False, indent=2)
        
        return certificate_id

# Инициализация конфигурации
test_config = TestConfig()

def get_test_config():
    return test_config

# Эндпоинт
@app.post(
    "/test/submit",
    response_model=CertificateResponse,
    status_code=status.HTTP_200_OK,
    summary="Отправка результатов теста",
    description="Принимает баллы за тест и возвращает сертификат, если результат превышает проходной порог"
)
async def submit_test_results(
    submission: TestSubmission,
    config: TestConfig = Depends(get_test_config)
):
    """
    Обработка отправки результатов теста.
    
    - **user_id**: Идентификатор пользователя
    - **test_id**: Идентификатор теста
    - **score**: Набранные баллы (0-100)
    
    Возвращает информацию о сертификате, если тест пройден.
    """
    try:
        # Получаем проходной порог из серверных данных
        passing_threshold = config.get_passing_threshold(submission.test_id)
        
        # Проверяем, пройден ли тест
        passed = submission.score >= passing_threshold
        
        # Формируем базовый ответ
        response_data = {
            "user_id": submission.user_id,
            "test_id": submission.test_id,
            "score": submission.score,
            "passing_threshold": passing_threshold,
            "passed": passed,
            "issue_date": datetime.now().isoformat(),
            "download_url": None
        }
        
        # Если тест пройден, генерируем сертификат
        if passed:
            certificate_data = {
                **response_data,
                "certificate_title": f"Сертификат о прохождении теста {submission.test_id}",
                "user_name": f"User_{submission.user_id}",  # В реальном приложении брали бы из БД
                "test_name": f"Тест {submission.test_id}",
                "expiration_date": None  # Можно добавить срок действия
            }
            
            # Сохраняем сертификат
            certificate_id = config.save_certificate(certificate_data)
            response_data["certificate_id"] = certificate_id
            
            # Генерируем URL для скачивания (в реальном приложении - полный URL)
            response_data["download_url"] = f"/certificates/download/{certificate_id}"
            
            return CertificateResponse(**response_data)
        else:
            # Если тест не пройден, возвращаем информацию без сертификата
            response_data["certificate_id"] = "none"
            return CertificateResponse(**response_data)
            
    except HTTPException:
        # Пробрасываем уже существующие HTTPException
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Некорректные данные: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

# Дополнительный эндпоинт для проверки порогов (для административных целей)
@app.get("/test/thresholds")
async def get_test_thresholds(config: TestConfig = Depends(get_test_config)):
    """Получение всех пороговых значений (для отладки и администрирования)"""
    return {
        "thresholds": config.passing_thresholds,
        "last_updated": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)