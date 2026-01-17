import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

# Инициализация декларативной базы
Base = declarative_base()

class User(Base):
    """Модель пользователя системы."""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    # Связь с токенами (один пользователь может иметь несколько попыток сброса в истории)
    reset_tokens = relationship("ResetToken", back_populates="user")

class ResetToken(Base):
    """Модель для хранения токенов восстановления пароля."""
    __tablename__ = 'reset_tokens'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    user = relationship("User", back_populates="reset_tokens")

    @property
    def is_expired(self) -> bool:
        """Проверка, истекло ли время действия токена."""
        return datetime.now(timezone.utc) > self.expires_at.replace(tzinfo=timezone.utc)

class PasswordResetManager:
    """
    Сервис для управления процессом восстановления доступа.
    Отвечает за генерацию токенов, их сохранение и формирование ссылок.
    """

    def __init__(self, db_session: Session, base_url: str = "https://example.com/reset"):
        """
        :param db_session: Сессия SQLAlchemy для работы с БД.
        :param base_url: Базовый URL страницы сброса пароля.
        """
        self._db = db_session
        self._base_url = base_url.rstrip('/')
        self._token_lifetime_minutes = 60  # Срок действия ссылки

    def _generate_secure_token(self) -> str:
        """Генерирует криптографически стойкий URL-безопасный токен."""
        return secrets.token_urlsafe(32)

    def create_reset_link(self, email: str) -> Optional[str]:
        """
        Создает токен в БД и возвращает полный URL для сброса пароля.
        
        Логика работы:
        1. Поиск пользователя по Email.
        2. Генерация уникального токена.
        3. Вычисление времени истечения (1 час).
        4. Сохранение записи в таблицу reset_tokens.
        5. Формирование строки URL.
        """
        # 1. Поиск пользователя
        user = self._db.query(User).filter(User.email == email).first()
        if not user:
            # В целях безопасности лучше не сообщать, что email не найден,
            # но для логики сервиса возвращаем None
            return None

        # 2. Подготовка данных токена
        token_str = self._generate_secure_token()
        expiration_time = datetime.now(timezone.utc) + timedelta(minutes=self._token_lifetime_minutes)

        # 3. Сохранение в БД
        reset_entry = ResetToken(
            user_id=user.id,
            token=token_str,
            expires_at=expiration_time
        )
        
        try:
            self._db.add(reset_entry)
            self._db.commit()
            
            # 4. Формирование URL
            return f"{self._base_url}?token={token_str}"
        
        except Exception as e:
            self._db.rollback()
            raise RuntimeError(f"Ошибка при сохранении токена восстановления: {e}")

    def verify_token(self, token: str) -> Optional[User]:
        """
        Проверяет валидность токена и возвращает пользователя.
        Используется на этапе, когда пользователь перешел по ссылке.
        """
        record = self._db.query(ResetToken).filter(ResetToken.token == token).first()
        
        if record and not record.is_expired:
            return record.user
        return None

# --- Демонстрация работы ---

if __name__ == "__main__":
    # Настройка базы данных в памяти
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        # Создаем тестового пользователя
        test_user = User(email="dev@example.com")
        session.add(test_user)
        session.commit()

        # Инициализируем менеджер
        manager = PasswordResetManager(session, base_url="https://myapp.io/auth/restore")

        # Генерируем ссылку
        email_to_reset = "dev@example.com"
        reset_url = manager.create_reset_link(email_to_reset)

        if reset_url:
            print(f"Ссылка для пользователя {email_to_reset}:")
            print(reset_url)
        else:
            print("Пользователь не найден.")

        # Эмуляция проверки токена (извлечение из URL)
        incoming_token = reset_url.split('=')[1]
        user_found = manager.verify_token(incoming_token)
        
        if user_found:
            print(f"Токен валиден для пользователя: {user_found.email}")