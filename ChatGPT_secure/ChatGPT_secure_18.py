import re
from typing import Dict, List

from fastapi import FastAPI, HTTPException, status, Depends
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import (
    declarative_base,
    relationship,
    sessionmaker,
    Session,
)


# =========================
# DATABASE SETUP
# =========================

DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# =========================
# DATABASE MODELS
# =========================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    correct_answer = Column(String, nullable=False)


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    score = Column(Integer, nullable=False)
    content = Column(String, nullable=False)

    user = relationship("User")


Base.metadata.create_all(engine)


# =========================
# AUTH MOCK
# =========================

def get_current_user(db: Session = Depends(SessionLocal)) -> User:
    user = db.query(User).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return user


# =========================
# Pydantic SCHEMAS
# =========================

class AnswerSubmission(BaseModel):
    question_id: int
    answer: str

    model_config = ConfigDict(extra="forbid")


class TestSubmissionRequest(BaseModel):
    answers: List[AnswerSubmission] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid")


class CertificateResponse(BaseModel):
    certificate_id: int
    score: int
    content: str


# =========================
# UTILS
# =========================

_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9\s.,-]")


def sanitize_text(value: str) -> str:
    """
    Удаляет опасные символы из сертификата.
    """
    return _SANITIZE_PATTERN.sub("", value)


# =========================
# SERVICE
# =========================

class OnlineTestService:
    """
    Сервис онлайн-тестирования и генерации сертификатов.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def process_test(
        self,
        user: User,
        submission: TestSubmissionRequest,
    ) -> Certificate:
        questions = self._load_questions(submission)
        score = self._calculate_score(questions, submission)
        certificate = self._generate_certificate(user, score)

        self._db.add(certificate)
        self._db.commit()
        return certificate

    def _load_questions(
        self,
        submission: TestSubmissionRequest,
    ) -> Dict[int, Question]:
        question_ids = [a.question_id for a in submission.answers]
        questions = (
            self._db.query(Question)
            .filter(Question.id.in_(question_ids))
            .all()
        )

        if len(questions) != len(set(question_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Некорректные вопросы",
            )

        return {q.id: q for q in questions}

    def _calculate_score(
        self,
        questions: Dict[int, Question],
        submission: TestSubmissionRequest,
    ) -> int:
        score = 0

        for answer in submission.answers:
            correct = questions[answer.question_id].correct_answer
            if answer.answer.strip() == correct:
                score += 1

        return score

    def _generate_certificate(self, user: User, score: int) -> Certificate:
        raw_content = (
            f"Certificate of Completion\n"
            f"User: {user.username}\n"
            f"Score: {score}"
        )

        clean_content = sanitize_text(raw_content)

        return Certificate(
            user_id=user.id,
            score=score,
            content=clean_content,
        )


# =========================
# FASTAPI APP
# =========================

app = FastAPI(
    title="Online Testing System",
    version="1.0.0",
)


# =========================
# ENDPOINT
# =========================

@app.post(
    "/test/submit",
    response_model=CertificateResponse,
)
def submit_test(
    submission: TestSubmissionRequest,
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        service = OnlineTestService(db)
        certificate = service.process_test(user, submission)

        return CertificateResponse(
            certificate_id=certificate.id,
            score=certificate.score,
            content=certificate.content,
        )
    finally:
        db.close()
