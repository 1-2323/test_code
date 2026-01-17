import time
import redis
from typing import Optional, Tuple
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Настройки безопасности
MAX_ATTEMPTS = 5
LOCK_TIME_SECONDS = 600  # 10 минут

# Инициализация хеширования и Redis
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)

class AuthService:
    """
    Сервис аутентификации с защитой от брутфорса.
    Использует Redis для отслеживания попыток входа.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def _get_attempts_key(self, username: str) -> str:
        return f"auth_attempts:{username}"

    def _get_lock_key(self, username: str) -> str:
        return f"auth_lock:{username}"

    def check_auth(self, username: str, password: str) -> Tuple[bool, str]:
        """
        Проверка учетных данных с логикой блокировки.
        Возвращает (успех, сообщение).
        """
        lock_key = self._get_lock_key(username)
        attempts_key = self._get_attempts_key(username)

        # 1. Проверка: не заблокирован ли аккаунт
        if r.exists(lock_key):
            ttl = r.ttl(lock_key)
            return False, f"Аккаунт заблокирован. Попробуйте через {ttl} сек."

        # 2. Поиск пользователя в БД
        user = self.db.query(User).filter(User.username == username).first()
        
        # 3. Валидация пароля
        if user and pwd_context.verify(password, user.password_hash):
            # Успешный вход: сбрасываем счетчик попыток
            r.delete(attempts_key)
            return True, "Успешный вход"

        # 4. Обработка неудачной попытки
        attempts = r.incr(attempts_key)
        if attempts == 1:
            r.expire(attempts_key, 3600) # Счетчик живет час

        if attempts >= MAX_ATTEMPTS:
            r.setex(lock_key, LOCK_TIME_SECONDS, "locked")
            r.delete(attempts_key)
            return False, "Слишком много неудачных попыток. Аккаунт заблокирован."

        return False, f"Неверный логин или пароль. Осталось попыток: {MAX_ATTEMPTS - attempts}"

# --- Пример интеграции ---

if __name__ == "__main__":
    # Настройка тестовой БД
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        # Создаем тестового пользователя
        hashed = pwd_context.hash("secret123")
        test_user = User(username="admin", password_hash=hashed)
        session.add(test_user)
        session.commit()

        auth = AuthService(session)

        # Симуляция неудачных попыток
        for i in range(6):
            success, msg = auth.check_auth("admin", "wrong_pass")
            print(f"Попытка {i+1}: {msg}")