import secrets
import string
import logging
from typing import Optional, Tuple, Final
from sqlalchemy import Column, Integer, String, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from passlib.context import CryptContext

# Настройка безопасного хеширования
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

Base = declarative_base()

class User(Base):
    """Модель пользователя с флагом принудительной смены пароля."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="user")
    must_change_password = Column(Boolean, default=True)


class SystemBootstrapper:
    """
    Скрипт первичной инициализации системы. 
    Создает суперпользователя с безопасными настройками.
    """

    DEFAULT_ADMIN_NAME: Final[str] = "admin_root"

    def __init__(self, db_url: str = "sqlite:///app.db"):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.logger = logging.getLogger("Bootstrapper")

    def _generate_secure_password(self, length: int = 16) -> str:
        """
        Генерирует криптографически стойкий пароль.
        Включает буквы, цифры и спецсимволы.
        """
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def setup_admin(self, custom_password: Optional[str] = None) -> Tuple[str, str]:
        """
        Создает учетную запись администратора. 
        Возвращает имя пользователя и временный пароль в открытом виде (для вывода в консоль).
        """
        session: Session = self.SessionLocal()
        try:
            # Проверка, существует ли уже админ
            existing_admin = session.query(User).filter(User.role == "admin").first()
            if existing_admin:
                self.logger.info("Admin account already exists. Skipping bootstrap.")
                return existing_admin.username, "[PROTECTED]"

            # Генерация пароля, если не задан вручную
            temp_password = custom_password or self._generate_secure_password()
            hashed_pwd = pwd_context.hash(temp_password)

            new_admin = User(
                username=self.DEFAULT_ADMIN_NAME,
                hashed_password=hashed_pwd,
                role="admin",
                must_change_password=True  # Флаг обязательной смены
            )

            session.add(new_admin)
            session.commit()
            
            return new_admin.username, temp_password

        except Exception as e:
            session.rollback()
            self.logger.error(f"Bootstrap failed: {str(e)}")
            raise
        finally:
            session.close()

# --- Логика запуска ---

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bootstrapper = SystemBootstrapper()
    
    user, pwd = bootstrapper.setup_admin()
    
    print("="*40)
    print("SYSTEM INITIALIZED SUCCESSFULLY")
    print(f"Username: {user}")
    print(f"Temporary Password: {pwd}")
    print("WARNING: You will be required to change this password on first login.")
    print("="*40)