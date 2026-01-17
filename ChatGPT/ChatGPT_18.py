from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session


# =========================
# Конфигурация БД
# =========================

DATABASE_URL: str = "sqlite:///./testing.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# =========================
# ORM-модели
# =========================

class TestQuestion(Base):
    """
    Вопрос теста с правильным ответом.
    """
    __tablename__ = "test_questions"

    id: int = Column(Integer, primary_key=True)
    correct_score: int = Column(Integer, nullable=False)


class Certificate(Base):
    """
    Сертификат о прохождении теста.
    """
    __tablename__ = "certificates"

    id: int = Column(Integer, primary_key=True)
    user_name: str = Column(String, nullable=False)
    total_score: int = Column(Integer, nullable=False)
    passed: bool = Column(Boolean, nullable=False)
    issued_at: datetime = Column(DateTime, default=datetime.utcnow)


# =========================
# Pydantic-модели
# =========================

class AnswerScore(BaseModel):
    """
    Балл за конкретный вопрос.
    """
    question_id: int
    score: int


class TestSubmissionRequest(BaseModel):
    """
    Запрос на отправку теста.
    """
    user_name: str
    answers: List[AnswerScore] = Field(..., min_items=1)


class CertificateResponse(BaseModel):
    """
    Ответ API с данными сертификата.
    """
    certificate_id: int
    user_name: str
    total_score: int
    passed: bool
    issued_at: datetime


# =========================
# Репозитории
# =========================

class QuestionRepository:
    """
    Репозиторий вопросов теста.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_correct_score(self, question_id: int) -> int:
        question = (
            self._db.query(TestQuestion)
            .filter(TestQuestion.id == question_id)
            .first()
        )
        if not question:
            raise HTTPException(
                status_code=404,
                detail=f"Question {question_id} not found",
            )
        return question.correct_score


class CertificateRepository:
    """
    Репозиторий сертификатов.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        user_name: str,
        total_score: int,
        passed: bool,
    ) -> Certificate:
        certificate = Certificate(
            user_name=user_name,
            total_score=total_score,
            passed=passed,
        )
        self._db.add(certificate)
        self._db.commit()
        self._db.refresh(certificate)
        return certificate


# =========================
# Сервис тестирования
# =========================

class OnlineTestProcessor:
    """
    Сервис обработки результатов онлайн-тестирования.
    """

    PASS_THRESHOLD: int = 70

    def __init__(
        self,
        question_repository: QuestionRepository,
        certificate_repository: CertificateRepository,
    ) -> None:
        self._questions = question_repository
        self._certificates = certificate_repository

    def evaluate(
        self,
        user_name: str,
        answers: List[AnswerScore],
    ) -> Certificate:
        """
        Алгоритм:
        1. Сверка ответов с правильными баллами
        2. Подсчёт итогового результата
        3. Генерация сертификата
        """
        total_score: int = 0
        max_score: int = 0

        for answer in answers:
            correct_score = self._questions.get_correct_score(
                answer.question_id
            )
            max_score += correct_score
            total_score += min(answer.score, correct_score)

        percentage: int = int((total_score / max_score) * 100)
        passed: bool = percentage >= self.PASS_THRESHOLD

        return self._certificates.create(
            user_name=user_name,
            total_score=percentage,
            passed=passed,
        )


# =========================
# Dependency
# =========================

def get_db() -> Session:
    """
    Dependency для сессии БД.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================
# FastAPI-приложение
# =========================

app = FastAPI(title="Online Testing System")


@app.post("/tests/submit", response_model=CertificateResponse)
def submit_test(
    request: TestSubmissionRequest,
    db: Session = SessionLocal(),
) -> CertificateResponse:
    """
    Эндпоинт отправки результатов теста.
    """
    question_repo = QuestionRepository(db)
    certificate_repo = CertificateRepository(db)
    processor = OnlineTestProcessor(
        question_repo,
        certificate_repo,
    )

    certificate = processor.evaluate(
        user_name=request.user_name,
        answers=request.answers,
    )

    return CertificateResponse(
        certificate_id=certificate.id,
        user_name=certificate.user_name,
        total_score=certificate.total_score,
        passed=certificate.passed,
        issued_at=certificate.issued_at,
    )


# =========================
# Инициализация БД
# =========================

def init_database() -> None:
    """
    Создаёт таблицы БД.
    """
    Base.metadata.create_all(bind=engine)
