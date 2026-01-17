import base64
from typing import Any, Optional
from cryptography.fernet import Fernet
from sqlalchemy import Column, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Инициализация базы SQLAlchemy
Base = declarative_base()

class EncryptionEngine:
    """
    Класс-утилита для выполнения операций шифрования и дешифрования.
    Использует алгоритм Fernet для обеспечения целостности и конфиденциальности.
    """
    def __init__(self, master_key: str):
        """
        :param master_key: Ключ Fernet (32 байта, кодированные base64).
        """
        try:
            self._fernet = Fernet(master_key.encode())
        except Exception as e:
            raise ValueError(f"Некорректный ключ шифрования: {e}")

    def encrypt(self, plain_text: str) -> str:
        """Шифрует строку и возвращает строку в формате base64."""
        if not plain_text:
            return plain_text
        return self._fernet.encrypt(plain_text.encode()).decode()

    def decrypt(self, cipher_text: str) -> str:
        """Расшифровывает строку base64 и возвращает исходный текст."""
        if not cipher_text:
            return cipher_text
        return self._fernet.decrypt(cipher_text.encode()).decode()

class UserProfile(Base):
    """
    Модель профиля пользователя.
    Поля с чувствительными данными хранятся в БД в зашифрованном виде.
    """
    __tablename__ = 'user_profiles'

    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False)
    
    # Эти поля будут содержать зашифрованные строки в БД
    _card_number = Column("card_number", Text)
    _tax_id = Column("tax_id", Text)

    def __init__(self, username: str, **kwargs):
        self.username = username
        super().__init__(**kwargs)

class SensitiveDataProtector:
    """
    Сервис-прослойка для управления доступом к зашифрованным полям.
    Реализует логику прозрачного преобразования данных.
    """
    def __init__(self, master_key: str):
        self._engine = EncryptionEngine(master_key)

    def protect_profile(self, profile: UserProfile, card: str, tax_id: str) -> None:
        """
        Автоматически шифрует и устанавливает значения в модель.
        """
        profile._card_number = self._engine.encrypt(card)
        profile._tax_id = self._engine.encrypt(tax_id)

    def reveal_card(self, profile: UserProfile) -> str:
        """Расшифровывает и возвращает номер карты."""
        return self._engine.decrypt(profile._card_number)

    def reveal_tax_id(self, profile: UserProfile) -> str:
        """Расшифровывает и возвращает ИНН/налоговый ID."""
        return self._engine.decrypt(profile._tax_id)

# --- Пример работы модуля ---

if __name__ == "__main__":
    # 1. Генерация ключа (в продакшене должен храниться в ENV или Vault)
    # Ключ можно создать через Fernet.generate_key()
    KEY = base64.urlsafe_b64encode(b"a_very_secret_32_byte_key_123456").decode()

    # 2. Настройка БД
    db_engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(db_engine)
    Session = sessionmaker(bind=db_engine)

    # 3. Работа с протектором
    protector = SensitiveDataProtector(KEY)
    
    with Session() as session:
        # Создание пользователя
        user = UserProfile(username="ivan_ivanov")
        
        # Данные шифруются перед сохранением
        protector.protect_profile(
            user, 
            card="4242-4242-4242-4242", 
            tax_id="7712345678"
        )
        
        session.add(user)
        session.commit()

        # Проверка: что лежит в БД на самом деле?
        raw_data = session.execute(f"SELECT card_number FROM user_profiles WHERE id={user.id}").scalar()
        print(f"Запись в БД (encrypted): {raw_data[:20]}...")

        # 4. Чтение и расшифровка
        db_user = session.query(UserProfile).first()
        print(f"Пользователь: {db_user.username}")
        print(f"Расшифрованная карта: {protector.reveal_card(db_user)}")
        print(f"Расшифрованный ИНН: {protector.reveal_tax_id(db_user)}")