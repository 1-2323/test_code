import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Base = declarative_base()

class User(Base):
    """Модель пользователя с данными для восстановления."""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)
    phone_number = Column(String)
    security_question_answer_hash = Column(String)  # Ответ хранится в виде хеша

class RecoverySession(Base):
    """Модель сессии восстановления для отслеживания этапов MFA."""
    __tablename__ = 'recovery_sessions'
    
    id = Column(String, primary_key=True)  # UUID сессии
    user_id = Column(Integer, ForeignKey('users.id'))
    sms_code = Column(String)
    is_question_verified = Column(Integer, default=0) # 0 - нет, 1 - да
    expires_at = Column(DateTime)

class MFAAccountRecoveryService:
    """
    Сервис многофакторного восстановления аккаунта.
    Процесс: Секретный вопрос -> SMS код -> Смена пароля.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def _hash_value(self, value: str) -> str:
        """Хеширование для защиты ответов и паролей."""
        return hashlib.sha256(value.lower().strip().encode()).hexdigest()

    def step_1_verify_question(self, user_id: int, answer: str) -> Optional[str]:
        """
        Первый этап: Проверка секретного вопроса.
        При успехе генерирует SMS-код и создает сессию.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user or self._hash_value(answer) != user.security_question_answer_hash:
            return None

        # Генерация 6-значного кода и сессии
        session_id = secrets.token_hex(16)
        code = str(secrets.randbelow(900000) + 100000)
        expiry = datetime.now(timezone.utc) + timedelta(minutes=10)

        new_session = RecoverySession(
            id=session_id,
            user_id=user.id,
            sms_code=code,
            is_question_verified=1,
            expires_at=expiry
        )
        
        # Симуляция отправки SMS
        print(f"[SMS Service] Код {code} отправлен на номер {user.phone_number}")
        
        self.db.add(new_session)
        self.db.commit()
        return session_id

    def step_2_reset_password(self, session_id: str, sms_code: str, new_password: str) -> bool:
        """
        Второй этап: Проверка SMS и финальная смена пароля.
        Требует валидную сессию с пройденным первым этапом.
        """
        session_record = self.db.query(RecoverySession).filter(
            RecoverySession.id == session_id
        ).first()

        # Валидация сессии: существование, этап 1, код, время
        if not session_record or not session_record.is_question_verified:
            return False
        
        if session_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return False

        if session_record.sms_code != sms_code:
            return False

        # Смена пароля пользователя
        user = self.db.query(User).filter(User.id == session_record.user_id).first()
        if user:
            user.password_hash = self._hash_value(new_password)
            
            # Удаление сессии после использования
            self.db.delete(session_record)
            self.db.commit()
            return True
        
        return False

# --- Тестовый сценарий ---
if __name__ == "__main__":
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        # Регистрация тестового пользователя
        ans_hash = hashlib.sha256(b"barsik").hexdigest()
        test_user = User(id=1, username="admin", phone_number="+79991234567", security_question_answer_hash=ans_hash)
        db.add(test_user)
        db.commit()

        service = MFAAccountRecoveryService(db)

        # 1. Попытка восстановить (вопрос: Как зовут кота?)
        sid = service.step_1_verify_question(1, "barsik")
        
        if sid:
            # 2. Ввод SMS из логов и нового пароля
            # В реальном коде код придет из RecoverySession.sms_code
            current_session = db.query(RecoverySession).filter(RecoverySession.id == sid).first()
            success = service.step_2_reset_password(sid, current_session.sms_code, "NewSecurePass123")
            print(f"Результат восстановления: {'Успех' if success else 'Ошибка'}")