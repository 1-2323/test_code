import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy import Column, Integer, String, Boolean, Float, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Base = declarative_base()

class Question(Base):
    """Модель вопроса с правильным ответом (хранится на сервере)."""
    __tablename__ = 'questions'
    id = Column(Integer, primary_key=True)
    text = Column(String, nullable=False)
    correct_option_id = Column(Integer, nullable=False)
    points = Column(Integer, default=1)

class QuizResult(Base):
    """Модель результата теста и выданного сертификата."""
    __tablename__ = 'quiz_results'
    id = Column(Integer, primary_key=True)
    user_name = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    passed = Column(Boolean, default=False)
    certificate_id = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class CertificateGenerator:
    """Генератор текстового представления сертификата."""
    
    @staticmethod
    def generate(user_name: str, score: float, cert_id: str) -> Dict[str, Any]:
        return {
            "title": "СЕРТИФИКАТ О ПРОХОЖДЕНИИ ТЕСТА",
            "recipient": user_name,
            "final_score": f"{score}%",
            "verification_code": cert_id,
            "issue_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Valid"
        }

class OnlineTestingSystem:
    """Сервис проверки ответов и управления тестированием."""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.pass_threshold = 70.0  # Порог прохождения в процентах

    def process_submission(self, user_name: str, user_answers: Dict[int, int]) -> Dict[str, Any]:
        """
        Принимает ответы от клиента, сверяет их и выдает результат.
        :param user_answers: Словарь {question_id: selected_option_id}
        """
        # 1. Получаем правильные ответы для переданных вопросов
        question_ids = list(user_answers.keys())
        questions = self.db.query(Question).filter(Question.id.in_(question_ids)).all()
        
        if not questions:
            raise ValueError("Вопросы не найдены в базе данных.")

        total_available_points = sum(q.points for q in questions)
        user_points = 0

        # 2. Сверка ответов (Server-side verification)
        for q in questions:
            if user_answers.get(q.id) == q.correct_option_id:
                user_points += q.points

        # 3. Расчет результата
        final_percentage = (user_points / total_available_points) * 100
        is_passed = final_percentage >= self.pass_threshold
        cert_id = str(uuid.uuid4()) if is_passed else None

        # 4. Сохранение результата в БД
        new_result = QuizResult(
            user_name=user_name,
            score=final_percentage,
            passed=is_passed,
            certificate_id=cert_id
        )
        
        try:
            self.db.add(new_result)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise RuntimeError(f"Ошибка сохранения результата: {e}")

        # 5. Формирование ответа
        response = {
            "user": user_name,
            "score": final_percentage,
            "passed": is_passed,
            "certificate": None
        }

        if is_passed:
            response["certificate"] = CertificateGenerator.generate(
                user_name, final_percentage, cert_id
            )

        return response

# --- Пример работы ---
if __name__ == "__main__":
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        # Инициализация вопросов на сервере
        session.add_all([
            Question(id=1, text="2+2?", correct_option_id=4, points=5),
            Question(id=2, text="Столица Франции?", correct_option_id=1, points=5)
        ])
        session.commit()

        tester = OnlineTestingSystem(session)
        
        # Ответы от клиента (ID вопроса: ID выбранного варианта)
        client_submission = {1: 4, 2: 1} 
        
        result = tester.process_submission("Иван Иванов", client_submission)
        
        import json
        print(json.dumps(result, indent=4, ensure_ascii=False))