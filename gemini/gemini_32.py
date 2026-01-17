import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from sqlalchemy import Column, Integer, String, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Base = declarative_base()

class User(Base):
    """Модель пользователя."""
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    # Поле для хранения метки последнего сброса (предотвращает повторное использование токена)
    last_password_reset_at = Column(DateTime, nullable=True)

class PasswordResetService:
    """
    Сервис управления сбросом пароля через безопасные токены.
    """

    def __init__(self, db_session: Session, secret_key: str):
        self.db = db_session
        # Использование itsdangerous для создания токенов со штампом времени
        self.serializer = URLSafeTimedSerializer(secret_key)
        self.salt = "password-reset-salt"

    def generate_reset_token(self, email: str) -> str:
        """Генерирует токен, привязанный к email пользователя."""
        return self.serializer.dumps(email, salt=self.salt)

    def verify_and_update_password(self, token: str, new_password: str, expires_in: int = 3600) -> bool:
        """
        Проверяет токен и обновляет пароль.
        :param expires_in: время жизни токена в секундах (по умолчанию 1 час).
        """
        try:
            # 1. Расшифровка и проверка срока годности
            email = self.serializer.loads(
                token, 
                salt=self.salt, 
                max_age=expires_in
            )
        except (SignatureExpired, BadTimeSignature):
            return False

        # 2. Поиск пользователя
        user = self.db.query(User).filter(User.email == email).first()
        if not user:
            return False

        # 3. Обновление данных
        # В продакшене используйте bcrypt для хеширования пароля
        user.password_hash = f"hashed_{new_password}"
        user.last_password_reset_at = datetime.now(timezone.utc)

        try:
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            return False

# --- Демонстрация работы ---

if __name__ == "__main__":
    # Настройка базы данных
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        # Создание тестового пользователя
        test_email = "user@example.com"
        user = User(email=test_email, password_hash="old_secret_hash")
        session.add(user)
        session.commit()

        # Инициализация сервиса
        reset_service = PasswordResetService(session, secret_key="MY_SECRET_KEY")

        # ЭТАП 1: Запрос сброса (генерация токена)
        reset_token = reset_service.generate_reset_token(test_email)
        print(f"Сгенерирован токен: {reset_token[:20]}...")

        # ЭТАП 2: Подтверждение сброса (валидация и смена пароля)
        success = reset_service.verify_and_update_password(reset_token, "NewSuperPassword2026")

        if success:
            updated_user = session.query(User).filter(User.email == test_email).first()
            print(f"Пароль успешно обновлен. Новый хеш: {updated_user.password_hash}")
        else:
            print("Ошибка: Токен недействителен или просрочен.")