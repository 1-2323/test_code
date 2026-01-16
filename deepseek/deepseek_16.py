import secrets
import time
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import hashlib


class AccountRepository(ABC):
    """Абстрактный репозиторий для работы с данными аккаунта"""
    
    @abstractmethod
    def get_secret_question(self, user_id: str) -> Optional[str]:
        """Получить секретный вопрос пользователя"""
        pass
    
    @abstractmethod
    def verify_secret_answer(self, user_id: str, answer: str) -> bool:
        """Проверить ответ на секретный вопрос"""
        pass
    
    @abstractmethod
    def get_phone_number(self, user_id: str) -> Optional[str]:
        """Получить номер телефона пользователя"""
        pass
    
    @abstractmethod
    def update_password(self, user_id: str, new_password_hash: str) -> bool:
        """Обновить пароль пользователя"""
        pass


class SMSService(ABC):
    """Абстрактный сервис отправки SMS"""
    
    @abstractmethod
    def send_verification_code(self, phone_number: str, code: str) -> bool:
        """Отправить код верификации на телефон"""
        pass


class AccountRecoveryService:
    """Сервис восстановления аккаунта с многофакторной аутентификацией"""
    
    def __init__(
        self,
        account_repo: AccountRepository,
        sms_service: SMSService,
        code_validity_minutes: int = 10
    ):
        self.account_repo = account_repo
        self.sms_service = sms_service
        self.code_validity_minutes = code_validity_minutes
        self._verification_codes: Dict[str, Dict[str, Any]] = {}  # user_id -> {code, expiry}
    
    def start_recovery(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Начать процесс восстановления: получаем секретный вопрос
        
        Args:
            user_id: Идентификатор пользователя
            
        Returns:
            Tuple[успех, секретный вопрос или сообщение об ошибке]
        """
        secret_question = self.account_repo.get_secret_question(user_id)
        
        if not secret_question:
            return False, "Пользователь не найден"
        
        return True, secret_question
    
    def verify_secret_question(
        self, 
        user_id: str, 
        answer: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Проверить ответ на секретный вопрос и отправить SMS с кодом
        
        Args:
            user_id: Идентификатор пользователя
            answer: Ответ на секретный вопрос
            
        Returns:
            Tuple[успех, сообщение]
        """
        # Проверяем ответ на секретный вопрос
        if not self.account_repo.verify_secret_answer(user_id, answer):
            return False, "Неверный ответ на секретный вопрос"
        
        # Получаем номер телефона
        phone_number = self.account_repo.get_phone_number(user_id)
        if not phone_number:
            return False, "Номер телефона не привязан к аккаунту"
        
        # Генерируем и отправляем код верификации
        verification_code = self._generate_verification_code()
        expiry_time = datetime.now() + timedelta(minutes=self.code_validity_minutes)
        
        self._verification_codes[user_id] = {
            'code': verification_code,
            'expiry': expiry_time,
            'verified': False
        }
        
        # Отправляем SMS
        if self.sms_service.send_verification_code(phone_number, verification_code):
            return True, f"Код отправлен на номер {phone_number[-4:]}"
        else:
            return False, "Ошибка при отправке SMS"
    
    def verify_sms_code(self, user_id: str, code: str) -> Tuple[bool, str]:
        """
        Проверить код из SMS
        
        Args:
            user_id: Идентификатор пользователя
            code: Код из SMS
            
        Returns:
            Tuple[успех, сообщение]
        """
        if user_id not in self._verification_codes:
            return False, "Сначала пройдите проверку секретным вопросом"
        
        verification_data = self._verification_codes[user_id]
        
        # Проверяем срок действия кода
        if datetime.now() > verification_data['expiry']:
            del self._verification_codes[user_id]
            return False, "Срок действия кода истек"
        
        # Проверяем код
        if verification_data['code'] != code:
            return False, "Неверный код"
        
        # Помечаем как верифицированный
        verification_data['verified'] = True
        return True, "Код подтвержден"
    
    def reset_password(
        self, 
        user_id: str, 
        new_password: str
    ) -> Tuple[bool, str]:
        """
        Сбросить пароль после успешной верификации
        
        Args:
            user_id: Идентификатор пользователя
            new_password: Новый пароль
            
        Returns:
            Tuple[успех, сообщение]
        """
        if user_id not in self._verification_codes:
            return False, "Требуется пройти многофакторную аутентификацию"
        
        if not self._verification_codes[user_id]['verified']:
            return False, "Требуется подтвердить код из SMS"
        
        # Хешируем пароль
        password_hash = self._hash_password(new_password)
        
        # Обновляем пароль в базе данных
        if self.account_repo.update_password(user_id, password_hash):
            # Удаляем временные данные после успешного сброса
            del self._verification_codes[user_id]
            return True, "Пароль успешно изменен"
        
        return False, "Ошибка при изменении пароля"
    
    def _generate_verification_code(self, length: int = 6) -> str:
        """Генерация случайного цифрового кода"""
        code = ''.join([str(secrets.randbelow(10)) for _ in range(length)])
        return code
    
    def _hash_password(self, password: str) -> str:
        """Хеширование пароля"""
        # Используем SHA-256 с солью для безопасности
        salt = secrets.token_hex(16)
        hash_object = hashlib.sha256((password + salt).encode())
        return f"{hash_object.hexdigest()}:{salt}"


# Пример использования
if __name__ == "__main__":
    # Заглушки для примера
    class MockAccountRepository(AccountRepository):
        def get_secret_question(self, user_id: str) -> Optional[str]:
            return "Девичья фамилия матери?"
        
        def verify_secret_answer(self, user_id: str, answer: str) -> bool:
            return answer == "Иванова"
        
        def get_phone_number(self, user_id: str) -> Optional[str]:
            return "+79001234567"
        
        def update_password(self, user_id: str, new_password_hash: str) -> bool:
            print(f"Пароль обновлен для {user_id}")
            return True
    
    class MockSMSService(SMSService):
        def send_verification_code(self, phone_number: str, code: str) -> bool:
            print(f"SMS отправлен на {phone_number}: Ваш код: {code}")
            return True
    
    # Создаем сервис
    recovery_service = AccountRecoveryService(
        account_repo=MockAccountRepository(),
        sms_service=MockSMSService()
    )
    
    # Пример процесса восстановления
    user_id = "user123"
    
    # 1. Начало восстановления
    success, result = recovery_service.start_recovery(user_id)
    if success:
        print(f"Секретный вопрос: {result}")
    
    # 2. Проверка секретного вопроса
    success, message = recovery_service.verify_secret_question(user_id, "Иванова")
    print(message)
    
    # 3. Проверка кода из SMS (в реальном приложении код вводит пользователь)
    # Для примера, нужно сначала посмотреть код в консоли