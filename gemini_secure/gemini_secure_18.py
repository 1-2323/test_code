import uuid
from datetime import datetime
from typing import Dict, List, Final, Any
from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, Field, field_validator


# --- Модели данных (Pydantic) ---

class User(BaseModel):
    """Схема текущего авторизованного пользователя."""
    id: int
    full_name: str
    is_active: bool


class SubmissionRequest(BaseModel):
    """
    Схема приема ответов от клиента. 
    Принимает только ID вопросов и выбранные варианты.
    """
    test_id: str
    answers: Dict[int, str] = Field(..., description="Map of question_id to selected_option")

    @field_validator("answers")
    @classmethod
    def check_not_empty(cls, v: Dict) -> Dict:
        if not v:
            raise ValueError("Answers cannot be empty")
        return v


class Certificate(BaseModel):
    """Схема итогового сертификата."""
    certificate_id: str
    user_name: str
    test_title: str
    score_percentage: float
    issued_at: datetime
    is_valid: bool


# --- Сервис логики тестирования ---

class TestingService:
    """
    Сервис для проведения тестов. Все расчеты и сверка ответов 
    происходят в изолированных методах на стороне сервера.
    """

    def __init__(self) -> None:
        # Имитация БД: Правильные ответы скрыты от клиента
        self._keys_db: Final[Dict[str, Any]] = {
            "math_101": {
                "title": "Basic Mathematics",
                "min_passing_score": 70.0,
                "answers": {
                    1: "A",
                    2: "C",
                    3: "B",
                    4: "D"
                }
            }
        }

    def _sanitize_string(self, text: str) -> str:
        """Очистка строк для предотвращения инъекций в документ."""
        return "".join(char for char in text if char.isalnum() or char in " -_")

    async def process_submission(self, user: User, submission: SubmissionRequest) -> Certificate:
        """
        Сверяет ответы, считает баллы и выдает сертификат.
        """
        # 1. Проверка существования теста
        test_data = self._keys_db.get(submission.test_id)
        if not test_data:
            raise HTTPException(status_code=404, detail="Test not found")

        # 2. Сверка ответов (Server-side Only)
        correct_answers = test_data["answers"]
        total_questions = len(correct_answers)
        correct_count = 0

        for q_id, user_ans in submission.answers.items():
            if q_id in correct_answers:
                # Используем прямое сравнение на сервере
                if user_ans.strip().upper() == correct_answers[q_id]:
                    correct_count += 1

        # 3. Расчет результата
        score_pct = (correct_count / total_questions) * 100

        # 4. Проверка прав на получение сертификата (проходной балл)
        if score_pct < test_data["min_passing_score"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Score {score_pct}% is below passing threshold."
            )

        # 5. Генерация сертификата с очищенными данными
        return Certificate(
            certificate_id=str(uuid.uuid4()),
            user_name=self._sanitize_string(user.full_name),
            test_title=self._sanitize_string(test_data["title"]),
            score_percentage=round(score_pct, 2),
            issued_at=datetime.now(),
            is_valid=True
        )


# --- API Эндпоинты ---

app = FastAPI(title="Secure Testing Engine")
testing_service = TestingService()


async def get_current_user() -> User:
    """Имитация получения пользователя из JWT/Сессии."""
    return User(id=123, full_name="Ivan Petrov", is_active=True)


@app.post("/test/submit", response_model=Certificate)
async def submit_test(
    submission: SubmissionRequest,
    current_user: User = Depends(get_current_user)
) -> Certificate:
    """
    Эндпоинт принимает только выборы пользователя. 
    Никакие баллы или статусы 'правильно/неправильно' от клиента не принимаются.
    """
    if not current_user.is_active:
        raise HTTPException(status_code=401, detail="User account is disabled")

    return await testing_service.process_submission(current_user, submission)