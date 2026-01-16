from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from abc import ABC, abstractmethod
import json
from dataclasses import dataclass, asdict


@dataclass
class Question:
    """Вопрос теста"""
    question_id: str
    question_text: str
    question_type: str  # "single_choice", "multiple_choice", "text"
    options: Optional[List[str]] = None
    correct_answer: Any = None
    max_score: int = 10


@dataclass
class UserAnswer:
    """Ответ пользователя на вопрос"""
    question_id: str
    answer: Any  # Может быть строкой, списком и т.д.


@dataclass
class TestResult:
    """Результат тестирования"""
    user_id: str
    test_id: str
    total_score: int
    max_possible_score: int
    percentage: float
    answers: Dict[str, Dict[str, Any]]  # question_id -> {user_answer, correct_answer, score}
    passed: bool
    certificate_id: Optional[str] = None


@dataclass
class Certificate:
    """Сертификат о прохождении теста"""
    certificate_id: str
    user_id: str
    test_id: str
    user_name: str
    test_name: str
    score: int
    max_score: int
    percentage: float
    issue_date: datetime
    expiry_date: Optional[datetime] = None


class TestRepository(ABC):
    """Абстрактный репозиторий для работы с тестами"""
    
    @abstractmethod
    def get_test_questions(self, test_id: str) -> List[Question]:
        """Получить вопросы теста"""
        pass
    
    @abstractmethod
    def get_passing_score(self, test_id: str) -> int:
        """Получить минимальный проходной балл"""
        pass
    
    @abstractmethod
    def get_test_info(self, test_id: str) -> Dict[str, Any]:
        """Получить информацию о тесте"""
        pass


class CertificateGenerator(ABC):
    """Абстрактный генератор сертификатов"""
    
    @abstractmethod
    def generate_certificate(
        self,
        test_result: TestResult,
        user_name: str,
        test_name: str
    ) -> Certificate:
        """Сгенерировать сертификат"""
        pass
    
    @abstractmethod
    def save_certificate(self, certificate: Certificate) -> bool:
        """Сохранить сертификат"""
        pass


class OnlineTestingService:
    """Сервис онлайн-тестирования"""
    
    def __init__(
        self,
        test_repo: TestRepository,
        certificate_gen: CertificateGenerator,
        min_passing_percentage: float = 70.0
    ):
        self.test_repo = test_repo
        self.certificate_gen = certificate_gen
        self.min_passing_percentage = min_passing_percentage
    
    def process_test_submission(
        self,
        user_id: str,
        test_id: str,
        user_answers: List[UserAnswer]
    ) -> Tuple[bool, Optional[TestResult], str]:
        """
        Обработать результаты теста
        
        Args:
            user_id: Идентификатор пользователя
            test_id: Идентификатор теста
            user_answers: Ответы пользователя
            
        Returns:
            Tuple[успех, результат теста или None, сообщение]
        """
        try:
            # 1. Получаем вопросы теста
            questions = self.test_repo.get_test_questions(test_id)
            if not questions:
                return False, None, "Тест не найден"
            
            # 2. Проверяем соответствие количества ответов
            if len(user_answers) != len(questions):
                return False, None, "Количество ответов не соответствует количеству вопросов"
            
            # 3. Оцениваем ответы
            evaluated_answers = {}
            total_score = 0
            max_possible_score = sum(q.max_score for q in questions)
            
            for question in questions:
                user_answer = self._find_user_answer(user_answers, question.question_id)
                
                if user_answer:
                    score, is_correct = self._evaluate_answer(question, user_answer.answer)
                    
                    evaluated_answers[question.question_id] = {
                        'user_answer': user_answer.answer,
                        'correct_answer': question.correct_answer,
                        'score': score,
                        'max_score': question.max_score,
                        'is_correct': is_correct
                    }
                    
                    total_score += score
                else:
                    evaluated_answers[question.question_id] = {
                        'user_answer': None,
                        'correct_answer': question.correct_answer,
                        'score': 0,
                        'max_score': question.max_score,
                        'is_correct': False
                    }
            
            # 4. Рассчитываем процент
            percentage = (total_score / max_possible_score * 100) if max_possible_score > 0 else 0
            
            # 5. Проверяем, прошел ли пользователь тест
            passing_score = self.test_repo.get_passing_score(test_id)
            passed = total_score >= passing_score and percentage >= self.min_passing_percentage
            
            # 6. Создаем результат теста
            test_result = TestResult(
                user_id=user_id,
                test_id=test_id,
                total_score=total_score,
                max_possible_score=max_possible_score,
                percentage=percentage,
                answers=evaluated_answers,
                passed=passed
            )
            
            # 7. Генерируем сертификат, если тест пройден
            if passed:
                self._generate_certificate(test_result, user_id, test_id)
            
            return True, test_result, "Тест успешно обработан"
            
        except Exception as e:
            return False, None, f"Ошибка при обработке теста: {str(e)}"
    
    def _find_user_answer(
        self, 
        user_answers: List[UserAnswer], 
        question_id: str
    ) -> Optional[UserAnswer]:
        """Найти ответ пользователя на конкретный вопрос"""
        for answer in user_answers:
            if answer.question_id == question_id:
                return answer
        return None
    
    def _evaluate_answer(
        self, 
        question: Question, 
        user_answer: Any
    ) -> Tuple[int, bool]:
        """
        Оценить ответ пользователя
        
        Returns:
            Tuple[набранные баллы, правильный ли ответ]
        """
        if question.question_type == "single_choice":
            is_correct = str(user_answer) == str(question.correct_answer)
            return question.max_score if is_correct else 0, is_correct
        
        elif question.question_type == "multiple_choice":
            if not isinstance(user_answer, list) or not isinstance(question.correct_answer, list):
                return 0, False
            
            user_set = set(str(x) for x in user_answer)
            correct_set = set(str(x) for x in question.correct_answer)
            
            if user_set == correct_set:
                return question.max_score, True
            elif user_set.issubset(correct_set):
                # Частично правильный ответ
                partial_score = int((len(user_set) / len(correct_set)) * question.max_score)
                return partial_score, False
            else:
                return 0, False
        
        elif question.question_type == "text":
            # Для текстовых ответов - простейшая проверка (в реальности нужен NLP)
            user_answer_str = str(user_answer).strip().lower()
            correct_answer_str = str(question.correct_answer).strip().lower()
            
            is_correct = user_answer_str == correct_answer_str
            return question.max_score if is_correct else 0, is_correct
        
        else:
            return 0, False
    
    def _generate_certificate(
        self,
        test_result: TestResult,
        user_id: str,
        test_id: str
    ) -> None:
        """Сгенерировать и сохранить сертификат"""
        test_info = self.test_repo.get_test_info(test_id)
        
        # В реальном приложении здесь был бы запрос к сервису пользователей
        user_name = "Иван Иванов"  # Заглушка
        
        certificate = self.certificate_gen.generate_certificate(
            test_result=test_result,
            user_name=user_name,
            test_name=test_info.get('name', 'Неизвестный тест')
        )
        
        if self.certificate_gen.save_certificate(certificate):
            test_result.certificate_id = certificate.certificate_id
    
    def get_detailed_feedback(
        self, 
        test_result: TestResult
    ) -> Dict[str, Any]:
        """Получить детализированную обратную связь по тесту"""
        feedback = {
            'overall': {
                'score': test_result.total_score,
                'max_score': test_result.max_possible_score,
                'percentage': test_result.percentage,
                'passed': test_result.passed
            },
            'questions': []
        }
        
        for question_id, answer_data in test_result.answers.items():
            feedback['questions'].append({
                'question_id': question_id,
                'user_answer': answer_data['user_answer'],
                'correct_answer': answer_data['correct_answer'],
                'score': answer_data['score'],
                'max_score': answer_data['max_score'],
                'is_correct': answer_data['is_correct']
            })
        
        return feedback


# Пример использования
if __name__ == "__main__":
    # Заглушки для примера
    class MockTestRepository(TestRepository):
        def get_test_questions(self, test_id: str) -> List[Question]:
            return [
                Question(
                    question_id="q1",
                    question_text="Столица Франции?",
                    question_type="single_choice",
                    options=["Лондон", "Париж", "Берлин", "Мадрид"],
                    correct_answer="Париж",
                    max_score=10
                ),
                Question(
                    question_id="q2",
                    question_text="Какие языки программирования являются компилируемыми?",
                    question_type="multiple_choice",
                    options=["Python", "C++", "JavaScript", "Rust"],
                    correct_answer=["C++", "Rust"],
                    max_score=20
                )
            ]
        
        def get_passing_score(self, test_id: str) -> int:
            return 20
        
        def get_test_info(self, test_id: str) -> Dict[str, Any]:
            return {'name': 'Тест по географии и программированию'}
    
    class MockCertificateGenerator(CertificateGenerator):
        def generate_certificate(
            self,
            test_result: TestResult,
            user_name: str,
            test_name: str
        ) -> Certificate:
            now = datetime.now()
            return Certificate(
                certificate_id=f"CERT-{now.strftime('%Y%m%d')}-{test_result.user_id}",
                user_id=test_result.user_id,
                test_id=test_result.test_id,
                user_name=user_name,
                test_name=test_name,
                score=test_result.total_score,
                max_score=test_result.max_possible_score,
                percentage=test_result.percentage,
                issue_date=now,
                expiry_date=None
            )
        
        def save_certificate(self, certificate: Certificate) -> bool:
            print(f"Сертификат сохранен: {certificate.certificate_id}")
            return True
    
    # Создаем сервис
    testing_service = OnlineTestingService(
        test_repo=MockTestRepository(),
        certificate_gen=MockCertificateGenerator()
    )
    
    # Пример ответов пользователя
    user_answers = [
        UserAnswer(question_id="q1", answer="Париж"),
        UserAnswer(question_id="q2", answer=["C++", "Rust"])
    ]
    
    # Обработка теста
    success, result, message = testing_service.process_test_submission(
        user_id="user123",
        test_id="test1",
        user_answers=user_answers
    )
    
    if success:
        print(f"Тест обработан: {result.total_score}/{result.max_possible_score}")
        print(f"Процент: {result.percentage:.1f}%")
        print(f"Сертификат: {result.certificate_id}")
        
        # Получаем детализированную обратную связь
        feedback = testing_service.get_detailed_feedback(result)
        print(f"Обратная связь: {json.dumps(feedback, indent=2, ensure_ascii=False)}")