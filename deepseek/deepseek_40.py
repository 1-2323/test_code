import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum


class TransactionStatus(Enum):
    """Статусы транзакций"""
    STARTED = "started"
    BANK_DECLINED = "bank_declined"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"


class SecurityAuditLogger:
    """
    Система аудита безопасности для модуля платежей.
    Логирует критические события с указанием ID пользователя и суммы.
    """
    
    def __init__(self, log_file: str = "payment_audit.log"):
        """
        Инициализация логгера безопасности.
        
        Args:
            log_file: Путь к файлу логов
        """
        self.logger = logging.getLogger("PaymentSecurityAudit")
        self.logger.setLevel(logging.INFO)
        
        # Обработчик для записи в файл
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
    
    def log_transaction_event(
        self,
        event_type: str,
        user_id: int,
        amount: float,
        transaction_id: Optional[str] = None,
        status: Optional[TransactionStatus] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Логирование события транзакции.
        
        Args:
            event_type: Тип события
            user_id: ID пользователя
            amount: Сумма транзакции
            transaction_id: ID транзакции (опционально)
            status: Статус транзакции (опционально)
            details: Дополнительные детали (опционально)
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event_type,
            "user_id": user_id,
            "amount": amount,
            "transaction_id": transaction_id,
            "status": status.value if status else None,
            "details": details or {}
        }
        
        # Форматируем сообщение для лога
        message = json.dumps(log_data, ensure_ascii=False)
        
        # Логируем в зависимости от типа события
        if event_type == "bank_declined":
            self.logger.error(message)
        else:
            self.logger.info(message)
    
    def log_transaction_start(
        self,
        user_id: int,
        amount: float,
        transaction_id: str
    ) -> None:
        """Логирование начала транзакции"""
        self.log_transaction_event(
            event_type="transaction_started",
            user_id=user_id,
            amount=amount,
            transaction_id=transaction_id,
            status=TransactionStatus.STARTED
        )
    
    def log_bank_declined(
        self,
        user_id: int,
        amount: float,
        transaction_id: str,
        reason: str
    ) -> None:
        """Логирование отказа банка"""
        self.log_transaction_event(
            event_type="bank_declined",
            user_id=user_id,
            amount=amount,
            transaction_id=transaction_id,
            status=TransactionStatus.BANK_DECLINED,
            details={"reason": reason}
        )
    
    def log_status_change(
        self,
        user_id: int,
        amount: float,
        transaction_id: str,
        new_status: TransactionStatus,
        previous_status: TransactionStatus
    ) -> None:
        """Логирование изменения статуса транзакции"""
        self.log_transaction_event(
            event_type="status_changed",
            user_id=user_id,
            amount=amount,
            transaction_id=transaction_id,
            status=new_status,
            details={
                "previous_status": previous_status.value,
                "new_status": new_status.value
            }
        )


# Пример использования
if __name__ == "__main__":
    audit_logger = SecurityAuditLogger()
    
    # Пример логирования событий
    audit_logger.log_transaction_start(
        user_id=12345,
        amount=1000.50,
        transaction_id="txn_001"
    )
    
    audit_logger.log_bank_declined(
        user_id=12345,
        amount=1000.50,
        transaction_id="txn_001",
        reason="insufficient_funds"
    )
    
    audit_logger.log_status_change(
        user_id=12345,
        amount=1000.50,
        transaction_id="txn_001",
        new_status=TransactionStatus.FAILED,
        previous_status=TransactionStatus.PENDING
    )