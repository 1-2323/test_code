import secrets
import string
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    create_engine,
)
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    Session,
)
from passlib.context import CryptContext


# =========================
# DATABASE SETUP
# =========================

DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# =========================
# SECURITY
# =========================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    """
    Хеширует пароль с использованием соли.
    """
    return pwd_context.hash(password)


def generate_secure_password(length: int = 16) -> str:
    """
    Генерирует криптографически стойкий пароль.
    """
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return "".join(secrets.choice(alphabet) for _ in range(length))


# =========================
# DATABASE MODEL
# =========================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    force_password_change = Column(Boolean, default=False)


Base.metadata.create_all(engine)


# =========================
# BOOTSTRAPPER
# =========================

class SystemBootstrapper:
    """
    Скрипт первого запуска системы.
    Создаёт учётную запись администратора.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def run(
        self,
        admin_username: str,
        admin_password: Optional[str] = None,
    ) -> str:
        """
        Создаёт администратора, если он отсутствует.
        Возвращает сгенерированный пароль (если применимо).
        """
        if self._admin_exists(admin_username):
            return ""

        password = admin_password or generate_secure_password()
        password_hash = hash_password(password)

        admin = User(
            username=admin_username,
            password_hash=password_hash,
            is_admin=True,
            force_password_change=True,
        )

        self._db.add(admin)
        self._db.commit()

        return password if admin_password is None else ""

    def _admin_exists(self, username: str) -> bool:
        return (
            self._db.query(User)
            .filter(User.username == username)
            .first()
            is not None
        )


# =========================
# SCRIPT ENTRYPOINT
# =========================

if __name__ == "__main__":
    db = SessionLocal()
    try:
        bootstrapper = SystemBootstrapper(db)
        generated_password = bootstrapper.run(
            admin_username="admin",
            admin_password=None,
        )

        if generated_password:
            print("Admin account created.")
            print("Generated password:", generated_password)
        else:
            print("Admin account already exists.")
    finally:
        db.close()
