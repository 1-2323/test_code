import re
from typing import Final, Optional
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from passlib.context import CryptContext

# Настройка контекста хеширования: используем Argon2 с автоматической солью
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

Base = declarative_base()

class User(Base):
    """Модель пользователя для SQLAlchemy."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)


class UserRegistrationFlow:
    """
    Сервис регистрации, обеспечивающий валидацию, безопасность паролей
    и защиту от SQL-инъекций через ORM.
    """

    # Регулярное выражение для строгой проверки Email (RFC 5322)
    EMAIL_REGEX: Final[re.Pattern] = re.compile(
        r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
        r"@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
        re.IGNORECASE
    )

    def __init__(self, db_url: str = "sqlite:///:memory:"):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _validate_email(self, email: str) -> None:
        """Проверка соответствия email строгому шаблону."""
        if not self.EMAIL_REGEX.match(email):
            raise ValueError(f"Invalid email format: {email}")

    def _validate_password_strength(self, password: str) -> None:
        """
        Проверка сложности пароля:
        - Минимум 8 символов
        - Минимум одна заглавная буква
        - Минимум одна цифра
        - Минимум один спецсимвол
        """
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not any(char.isdigit() for char in password):
            raise ValueError("Password must contain at least one digit.")
        if not any(char.isupper() for char in password):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            raise ValueError("Password must contain at least one special character.")

    def _hash_password(self, password: str) -> str:
        """Хеширование пароля с использованием соли (Argon2)."""
        return pwd_context.hash(password)

    def register_user(self, email: str, password: str) -> User:
        """
        Основной бизнес-процесс регистрации нового пользователя.
        
        :param email: Электронная почта пользователя.
        :param password: Пароль в открытом виде.
        :return: Созданный объект User.
        :raises ValueError: Если валидация не пройдена или пользователь существует.
        """
        # 1. Валидация входных данных
        self._validate_email(email)
        self._validate_password_strength(password)

        session: Session = self.SessionLocal()
        try:
            # 2. Проверка уникальности (параметризованный запрос через ORM)
            existing_user = session.query(User).filter(User.email == email).first()
            if existing_user:
                raise ValueError(f"User with email {email} already exists.")

            # 3. Хеширование
            hashed_pwd = self._hash_password(password)

            # 4. Сохранение
            new_user = User(email=email, hashed_password=hashed_pwd)
            session.add(new_user)
            session.commit()
            session.refresh(new_user)
            
            return new_user
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def verify_login(self, email: str, password: str) -> bool:
        """Метод для проверки учетных данных при входе."""
        session: Session = self.SessionLocal()
        user = session.query(User).filter(User.email == email).first()
        session.close()

        if not user:
            return False

        return pwd_context.verify(password, user.hashed_password)