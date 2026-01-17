import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session


# =========================
# Конфигурация и БД
# =========================

DATABASE_URL: str = "sqlite:///./profiles.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# =========================
# Исключения
# =========================

class SensitiveDataError(Exception):
    """Базовое исключение работы с чувствительными данными."""
    pass


class EncryptionError(SensitiveDataError):
    """Ошибка шифрования."""
    pass


class DecryptionError(SensitiveDataError):
    """Ошибка расшифровки."""
    pass


# =========================
# Сервис защиты данных
# =========================

class SensitiveDataProtector:
    """
    Сервис для шифрования и расшифровки чувствительных данных.
    """

    NONCE_SIZE: int = 12

    def __init__(self, base64_key: str) -> None:
        self._key: bytes = self._decode_key(base64_key)
        self._aesgcm: AESGCM = AESGCM(self._key)

    def encrypt(self, value: str) -> str:
        """
        Шифрует строковое значение.
        """
        try:
            nonce: bytes = os.urandom(self.NONCE_SIZE)
            ciphertext: bytes = self._aesgcm.encrypt(
                nonce=nonce,
                data=value.encode("utf-8"),
                associated_data=None,
            )
            payload: bytes = nonce + ciphertext
            return base64.b64encode(payload).decode("utf-8")

        except Exception as exc:  # noqa: BLE001
            raise EncryptionError("Failed to encrypt value") from exc

    def decrypt(self, value: str) -> str:
        """
        Расшифровывает строковое значение.
        """
        try:
            payload: bytes = base64.b64decode(value)
            nonce: bytes = payload[:self.NONCE_SIZE]
            ciphertext: bytes = payload[self.NONCE_SIZE:]

            decrypted: bytes = self._aesgcm.decrypt(
                nonce=nonce,
                data=ciphertext,
                associated_data=None,
            )
            return decrypted.decode("utf-8")

        except Exception as exc:  # noqa: BLE001
            raise DecryptionError("Failed to decrypt value") from exc

    @staticmethod
    def _decode_key(encoded_key: str) -> bytes:
        """
        Декодирует и валидирует ключ шифрования.
        """
        key: bytes = base64.b64decode(encoded_key)

        if len(key) != 32:
            raise ValueError("Encryption key must be 32 bytes")

        return key


# =========================
# ORM-модель профиля
# =========================

class UserProfile(Base):
    """
    Профиль пользователя с чувствительными данными.
    """
    __tablename__ = "user_profiles"

    id: int = Column(Integer, primary_key=True)
    name: str = Column(String, nullable=False)
    encrypted_card_number: Optional[str] = Column(String, nullable=True)


# =========================
# Репозиторий профиля
# =========================

class UserProfileRepository:
    """
    Репозиторий профиля пользователя с автоматической
    защитой чувствительных данных.
    """

    def __init__(
        self,
        db: Session,
        protector: SensitiveDataProtector,
    ) -> None:
        self._db: Session = db
        self._protector: SensitiveDataProtector = protector

    def create(
        self,
        name: str,
        card_number: Optional[str],
    ) -> UserProfile:
        """
        Создаёт профиль пользователя с шифрованием карты.
        """
        encrypted_card: Optional[str] = (
            self._protector.encrypt(card_number)
            if card_number
            else None
        )

        profile = UserProfile(
            name=name,
            encrypted_card_number=encrypted_card,
        )

        self._db.add(profile)
        self._db.commit()
        self._db.refresh(profile)
        return profile

    def get_by_id(self, profile_id: int) -> Optional[dict]:
        """
        Возвращает профиль с расшифрованными данными.
        """
        profile: Optional[UserProfile] = (
            self._db.query(UserProfile)
            .filter(UserProfile.id == profile_id)
            .first()
        )

        if profile is None:
            return None

        decrypted_card: Optional[str] = (
            self._protector.decrypt(profile.encrypted_card_number)
            if profile.encrypted_card_number
            else None
        )

        return {
            "id": profile.id,
            "name": profile.name,
            "card_number": decrypted_card,
        }


# =========================
# Инициализация БД
# =========================

def init_database() -> None:
    """
    Создаёт таблицы БД.
    """
    Base.metadata.create_all(bind=engine)


