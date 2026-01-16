import json
import base64
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib
import logging

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class FinancialMessage:
    """Финансовое сообщение для обмена между микросервисами"""
    message_id: str
    sender_id: str
    receiver_id: str
    transaction_id: str
    amount: float
    currency: str = "USD"
    timestamp: str = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        """Инициализация после создания объекта"""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для сериализации"""
        return asdict(self)
    
    def to_json(self) -> str:
        """Сериализация в JSON строку"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class SignatureManager:
    """Менеджер для работы с цифровыми подписями"""
    
    def __init__(self, key_size: int = 2048):
        """
        Инициализация менеджера подписей
        
        Args:
            key_size: Размер ключа RSA в битах
        """
        self.key_size = key_size
    
    def generate_key_pair(self) -> tuple[str, str]:
        """
        Генерация пары приватный/публичный ключ
        
        Returns:
            Кортеж (private_key_pem, public_key_pem) в формате PEM
        """
        # Генерация приватного ключа
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=self.key_size,
            backend=default_backend()
        )
        
        # Получение публичного ключа из приватного
        public_key = private_key.public_key()
        
        # Сериализация в PEM формат
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')
        
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        
        return private_pem, public_pem
    
    def sign_message(self, message: str, private_key_pem: str) -> str:
        """
        Подпись сообщения приватным ключом
        
        Args:
            message: Сообщение для подписи
            private_key_pem: Приватный ключ в PEM формате
            
        Returns:
            Подпись в base64 формате
        """
        # Загрузка приватного ключа
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode('utf-8'),
            password=None,
            backend=default_backend()
        )
        
        # Создание подписи
        signature = private_key.sign(
            message.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        # Кодирование подписи в base64
        return base64.b64encode(signature).decode('utf-8')
    
    def verify_signature(
        self, 
        message: str, 
        signature: str, 
        public_key_pem: str
    ) -> bool:
        """
        Проверка подписи сообщения
        
        Args:
            message: Подписанное сообщение
            signature: Подпись в base64 формате
            public_key_pem: Публичный ключ в PEM формате
            
        Returns:
            True если подпись верна, иначе False
        """
        try:
            # Загрузка публичного ключа
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode('utf-8'),
                backend=default_backend()
            )
            
            # Декодирование подписи из base64
            signature_bytes = base64.b64decode(signature)
            
            # Проверка подписи
            public_key.verify(
                signature_bytes,
                message.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return True
            
        except (InvalidSignature, ValueError, TypeError) as e:
            logger.error(f"Signature verification failed: {e}")
            return False


class FinancialMessageSender:
    """Отправитель финансовых сообщений"""
    
    def __init__(self, sender_id: str, private_key_pem: str):
        """
        Инициализация отправителя
        
        Args:
            sender_id: Идентификатор отправителя
            private_key_pem: Приватный ключ для подписи
        """
        self.sender_id = sender_id
        self.private_key_pem = private_key_pem
        self.signature_manager = SignatureManager()
    
    def create_signed_message(
        self,
        receiver_id: str,
        transaction_id: str,
        amount: float,
        currency: str = "USD",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Создание и подпись финансового сообщения
        
        Returns:
            Словарь с сообщением и подписью
        """
        # Создаем финансовое сообщение
        message = FinancialMessage(
            message_id=self._generate_message_id(),
            sender_id=self.sender_id,
            receiver_id=receiver_id,
            transaction_id=transaction_id,
            amount=amount,
            currency=currency,
            metadata=metadata or {}
        )
        
        # Преобразуем в JSON
        message_json = message.to_json()
        
        # Создаем подпись
        signature = self.signature_manager.sign_message(
            message_json,
            self.private_key_pem
        )
        
        # Формируем итоговый пакет
        return {
            "message": message.to_dict(),
            "signature": signature,
            "algorithm": "RSA-PSS-SHA256"
        }
    
    def _generate_message_id(self) -> str:
        """Генерация уникального ID сообщения"""
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        return f"msg_{self.sender_id}_{timestamp}"


class FinancialMessageReceiver:
    """Получатель финансовых сообщений"""
    
    def __init__(self, receiver_id: str):
        """
        Инициализация получателя
        
        Args:
            receiver_id: Идентификатор получателя
        """
        self.receiver_id = receiver_id
        self.signature_manager = SignatureManager()
        # Словарь для хранения публичных ключей отправителей
        self.sender_public_keys: Dict[str, str] = {}
    
    def register_sender_public_key(self, sender_id: str, public_key_pem: str) -> None:
        """
        Регистрация публичного ключа отправителя
        
        Args:
            sender_id: Идентификатор отправителя
            public_key_pem: Публичный ключ отправителя
        """
        self.sender_public_keys[sender_id] = public_key_pem
        logger.info(f"Registered public key for sender: {sender_id}")
    
    def verify_and_process(
        self, 
        message_package: Dict[str, Any]
    ) -> tuple[bool, Optional[FinancialMessage], str]:
        """
        Проверка и обработка входящего сообщения
        
        Returns:
            Кортеж (успешность, сообщение, статус)
        """
        try:
            # Извлекаем данные из пакета
            message_dict = message_package.get("message")
            signature = message_package.get("signature")
            algorithm = message_package.get("algorithm")
            
            if not all([message_dict, signature, algorithm]):
                return False, None, "Missing required fields in message package"
            
            # Преобразуем обратно в JSON для проверки подписи
            message_json = json.dumps(message_dict, ensure_ascii=False, sort_keys=True)
            
            # Получаем информацию об отправителе
            sender_id = message_dict.get("sender_id")
            if not sender_id:
                return False, None, "Missing sender_id in message"
            
            # Проверяем наличие публичного ключа отправителя
            public_key_pem = self.sender_public_keys.get(sender_id)
            if not public_key_pem:
                return False, None, f"Unknown sender: {sender_id}"
            
            # Проверяем подпись
            if not self.signature_manager.verify_signature(
                message_json,
                signature,
                public_key_pem
            ):
                return False, None, "Invalid signature"
            
            # Создаем объект сообщения
            message = FinancialMessage(**message_dict)
            
            # Проверяем, что получатель верный
            if message.receiver_id != self.receiver_id:
                return False, message, "Message not intended for this receiver"
            
            # Логируем успешную проверку
            logger.info(
                f"Verified message {message.message_id} from {sender_id} "
                f"for transaction {message.transaction_id}"
            )
            
            return True, message, "Message verified successfully"
            
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Message processing error: {e}")
            return False, None, f"Processing error: {str(e)}"


# Пример использования
def example_usage() -> None:
    """Пример использования системы обмена сообщениями"""
    
    # Инициализация менеджера подписей
    signature_manager = SignatureManager()
    
    # Генерация ключей для отправителя
    private_key_pem, public_key_pem = signature_manager.generate_key_pair()
    
    # Создание отправителя
    sender = FinancialMessageSender(
        sender_id="bank_a",
        private_key_pem=private_key_pem
    )
    
    # Создание получателя
    receiver = FinancialMessageReceiver(receiver_id="bank_b")
    receiver.register_sender_public_key("bank_a", public_key_pem)
    
    # Отправка сообщения
    message_package = sender.create_signed_message(
        receiver_id="bank_b",
        transaction_id="txn_123456",
        amount=1500.75,
        currency="USD",
        metadata={"description": "Payment for services"}
    )
    
    logger.info(f"Sent message package: {message_package['message']['message_id']}")
    
    # Получение и проверка сообщения
    success, message, status = receiver.verify_and_process(message_package)
    
    if success and message:
        logger.info(f"Message verified: {status}")
        logger.info(f"Transaction: {message.transaction_id}, Amount: {message.amount} {message.currency}")
    else:
        logger.error(f"Message verification failed: {status}")


if __name__ == "__main__":
    example_usage()