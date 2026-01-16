"""
Сервис для восстановления доступа с генерацией токенов,
хранением их в БД и отправкой ссылок для сброса пароля.
"""

import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from urllib.parse import urljoin

# Настройка базы данных
DATABASE_URL = "sqlite:///reset_tokens.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class PasswordResetToken(Base):
    """Модель токена восстановления пароля."""
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    used_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<PasswordResetToken(id={self.id}, user_id={self.user_id})>"

    def is_expired(self) -> bool:
        """Проверяет, истек ли срок действия токена."""
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self) -> bool:
        """Проверяет, валиден ли токен."""
        return not self.is_used and not self.is_expired()


# Создаем таблицы
Base.metadata.create_all(bind=engine)


class TokenGenerator:
    """Генератор безопасных токенов."""
    
    @staticmethod
    def generate_token(length: int = 32) -> str:
        """
        Генерирует криптографически безопасный токен.
        
        Args:
            length: Длина токена в байтах
            
        Returns:
            Токен в hex формате
        """
        # Используем secrets для криптографически безопасной генерации
        token_bytes = secrets.token_bytes(length)
        return token_bytes.hex()
    
    @staticmethod
    def hash_token(token: str) -> str:
        """
        Создает хеш токена для безопасного хранения.
        
        Args:
            token: Исходный токен
            
        Returns:
            SHA-256 хеш токена
        """
        return hashlib.sha256(token.encode('utf-8')).hexdigest()


class EmailService:
    """Сервис для отправки email (заглушка для примера)."""
    
    def __init__(self, smtp_server: str = "smtp.example.com", 
                 smtp_port: int = 587,
                 sender_email: str = "noreply@example.com"):
        """
        Инициализация email сервиса.
        
        Args:
            smtp_server: SMTP сервер
            smtp_port: Порт SMTP сервера
            sender_email: Email отправителя
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
    
    def send_reset_email(self, to_email: str, reset_url: str) -> bool:
        """
        Отправляет email с ссылкой для сброса пароля.
        
        Args:
            to_email: Email получателя
            reset_url: URL для сброса пароля
            
        Returns:
            True если отправка успешна, иначе False
        """
        # В реальном проекте здесь будет реализация отправки через SMTP
        # Например, с использованием smtplib и email.message
        
        subject = "Восстановление пароля"
        body = f"""
        Здравствуйте!
        
        Вы запросили восстановление пароля. Для установки нового пароля 
        перейдите по ссылке: {reset_url}
        
        Ссылка действительна в течение 1 часа.
        
        Если вы не запрашивали восстановление пароля, проигнорируйте это письмо.
        
        С уважением,
        Команда поддержки
        """
        
        # Заглушка для примера
        print(f"[EMAIL] Отправка письма на {to_email}")
        print(f"[EMAIL] Тема: {subject}")
        print(f"[EMAIL] Ссылка: {reset_url}")
        print(f"[EMAIL] Тело письма: {body}")
        
        # В реальной реализации здесь будет код отправки email
        # return self._send_actual_email(to_email, subject, body)
        return True


class PasswordResetManager:
    """Основной сервис управления восстановлением пароля."""
    
    def __init__(self, 
                 db_session: Session,
                 base_url: str = "https://example.com/reset-password",
                 token_expiry_hours: int = 1):
        """
        Инициализация менеджера восстановления пароля.
        
        Args:
            db_session: Сессия SQLAlchemy
            base_url: Базовый URL для ссылок восстановления
            token_expiry_hours: Время жизни токена в часах
        """
        self.db = db_session
        self.base_url = base_url
        self.token_expiry_hours = token_expiry_hours
        self.token_generator = TokenGenerator()
        self.email_service = EmailService()
    
    def generate_reset_token(self, user_id: int) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Генерирует токен восстановления пароля.
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Кортеж (успех, токен, сообщение_об_ошибке)
        """
        # 1. Проверяем, нет ли активных токенов у пользователя
        active_tokens = self.db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.is_used == False,
            PasswordResetToken.expires_at > datetime.utcnow()
        ).all()
        
        # Отмечаем старые токены как использованные
        for token in active_tokens:
            token.is_used = True
            token.used_at = datetime.utcnow()
        
        try:
            # 2. Генерируем новый токен
            raw_token = self.token_generator.generate_token()
            token_hash = self.token_generator.hash_token(raw_token)
            
            # 3. Устанавливаем срок действия
            expires_at = datetime.utcnow() + timedelta(hours=self.token_expiry_hours)
            
            # 4. Сохраняем токен в БД
            reset_token = PasswordResetToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at
            )
            
            self.db.add(reset_token)
            self.db.commit()
            
            return True, raw_token, "Токен успешно создан"
            
        except Exception as e:
            self.db.rollback()
            return False, None, f"Ошибка при создании токена: {str(e)}"
    
    def create_reset_url(self, token: str) -> str:
        """
        Создает полный URL для восстановления пароля.
        
        Args:
            token: Токен восстановления
            
        Returns:
            Полный URL
        """
        return f"{self.base_url}?token={token}"
    
    def send_reset_email(self, user_id: int, user_email: str) -> Tuple[bool, str]:
        """
        Генерирует токен и отправляет email для восстановления.
        
        Args:
            user_id: ID пользователя
            user_email: Email пользователя
            
        Returns:
            Кортеж (успех, сообщение)
        """
        # 1. Генерируем токен
        success, token, message = self.generate_reset_token(user_id)
        
        if not success:
            return False, message
        
        # 2. Создаем URL
        reset_url = self.create_reset_url(token)
        
        # 3. Отправляем email
        email_sent = self.email_service.send_reset_email(user_email, reset_url)
        
        if email_sent:
            return True, f"Письмо с инструкциями отправлено на {user_email}"
        else:
            return False, "Не удалось отправить email"
    
    def validate_token(self, raw_token: str) -> Tuple[bool, Optional[int], str]:
        """
        Проверяет валидность токена восстановления.
        
        Args:
            raw_token: Токен для проверки
            
        Returns:
            Кортеж (валиден_ли, user_id, сообщение)
        """
        # Хешируем токен для поиска в БД
        token_hash = self.token_generator.hash_token(raw_token)
        
        # Ищем токен в БД
        reset_token = self.db.query(PasswordResetToken).filter(
            PasswordResetToken.token_hash == token_hash
        ).first()
        
        if not reset_token:
            return False, None, "Токен не найден"
        
        if reset_token.is_used:
            return False, None, "Токен уже был использован"
        
        if reset_token.is_expired():
            return False, None, "Срок действия токена истек"
        
        # Помечаем токен как использованный
        reset_token.is_used = True
        reset_token.used_at = datetime.utcnow()
        self.db.commit()
        
        return True, reset_token.user_id, "Токен валиден"
    
    def cleanup_expired_tokens(self) -> int:
        """
        Удаляет истекшие токены из базы данных.
        
        Returns:
            Количество удаленных токенов
        """
        expired_tokens = self.db.query(PasswordResetToken).filter(
            PasswordResetToken.expires_at <= datetime.utcnow()
        ).all()
        
        count = len(expired_tokens)
        
        for token in expired_tokens:
            self.db.delete(token)
        
        self.db.commit()
        
        return count


# Пример использования
if __name__ == "__main__":
    # Создаем сессию БД
    db = SessionLocal()
    
    # Инициализируем менеджер восстановления пароля
    reset_manager = PasswordResetManager(
        db_session=db,
        base_url="http://localhost:3000/reset-password"
    )
    
    # Пример: отправка email для восстановления
    user_id = 1
    user_email = "user@example.com"
    
    success, message = reset_manager.send_reset_email(user_id, user_email)
    print(f"Отправка email: {success} - {message}")
    
    # Пример: проверка токена
    # (В реальном случае токен будет получен из URL)
    sample_token = "sample_token_here"
    is_valid, user_id, validation_message = reset_manager.validate_token(sample_token)
    print(f"Валидация токена: {is_valid} - {validation_message}")
    
    # Очистка истекших токенов
    cleaned = reset_manager.cleanup_expired_tokens()
    print(f"Очищено истекших токенов: {cleaned}")
    
    # Закрываем сессию
    db.close()