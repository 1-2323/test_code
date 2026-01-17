import json
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature
from typing import Dict, Any, Tuple

class FinancialMessageSigner:
    """
    Компонент для подписи и верификации финансовых транзакций.
    Использует алгоритм Ed25519 (быстрый и современный стандарт).
    """

    def __init__(self):
        # В реальной системе ключи должны загружаться из защищенного хранилища (Vault/ENV)
        self.private_key = ed25519.Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()

    def sign_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Сериализует JSON, создает цифровую подпись и упаковывает всё в конверт.
        """
        # Важно: сортировка ключей гарантирует идентичность строки на обоих концах
        message_json = json.dumps(payload, sort_keys=True).encode('utf-8')
        
        # Генерация подписи
        signature = self.private_key.sign(message_json)
        
        # Кодируем в Base64 для передачи через JSON/HTTP
        signature_b64 = base64.b64encode(signature).decode('utf-8')
        
        return {
            "data": payload,
            "signature": signature_b64
        }

    @staticmethod
    def verify_payload(envelope: Dict[str, Any], public_key: ed25519.Ed25519PublicKey) -> bool:
        """
        Проверяет, соответствует ли подпись содержимому пакета 'data'.
        """
        try:
            # Извлечение данных и подписи
            payload = envelope.get("data")
            signature_b64 = envelope.get("signature")
            
            if not payload or not signature_b64:
                return False

            # Восстановление исходного байтового представления
            message_json = json.dumps(payload, sort_keys=True).encode('utf-8')
            signature = base64.b64decode(signature_b64)

            # Верификация
            public_key.verify(signature, message_json)
            return True
            
        except (InvalidSignature, ValueError, TypeError):
            return False

# --- Демонстрация работы между микросервисами ---

# 1. Сервис "Платежи" (Отправитель)
signer_service = FinancialMessageSigner()

transaction = {
    "transaction_id": "TX-99021",
    "amount": 1500.50,
    "currency": "USD",
    "sender_account": "ACC-123",
    "receiver_account": "ACC-456"
}

signed_packet = signer_service.sign_payload(transaction)
print("--- Сформированный пакет для отправки ---")
print(json.dumps(signed_packet, indent=2))

# 2. Сервис "Клиринг" (Получатель)
# Получатель должен иметь публичный ключ отправителя
sender_pub_key = signer_service.public_key

is_valid = FinancialMessageSigner.verify_payload(signed_packet, sender_pub_key)

print(f"\nРезультат проверки: {'✅ ВАЛИДНО' if is_valid else '❌ ОШИБКА ПОДПИСИ'}")

# Имитация попытки подделки данных злоумышленником
signed_packet["data"]["amount"] = 99999.99
is_valid_after_tamper = FinancialMessageSigner.verify_payload(signed_packet, sender_pub_key)
print(f"Результат после изменения суммы: {'✅ ВАЛИДНО' if is_valid_after_tamper else '❌ ОШИБКА ПОДПИСИ'}")