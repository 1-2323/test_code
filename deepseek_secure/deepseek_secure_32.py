from typing import Optional, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import sqlite3

class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    TRIAL = "trial"

class BillingCycle(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"

@dataclass
class Subscription:
    """Подписка пользователя."""
    id: str
    user_id: str
    plan_id: str
    status: SubscriptionStatus
    billing_cycle: BillingCycle
    started_at: datetime
    current_period_end: datetime
    cancelled_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None
    
    def is_active(self) -> bool:
        """Проверка активности подписки."""
        now = datetime.now()
        return (
            self.status == SubscriptionStatus.ACTIVE and
            self.current_period_end > now
        )
    
    def days_remaining(self) -> int:
        """Оставшиеся дни подписки."""
        now = datetime.now()
        if self.current_period_end > now:
            return (self.current_period_end - now).days
        return 0

class SubscriptionManager:
    """Менеджер подписок."""
    
    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация БД."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    billing_cycle TEXT NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    current_period_end TIMESTAMP NOT NULL,
                    cancelled_at TIMESTAMP,
                    trial_ends_at TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON subscriptions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON subscriptions(status)")
            conn.commit()
    
    def create_subscription(self, user_id: str, plan_id: str,
                          billing_cycle: BillingCycle,
                          trial_days: int = 0) -> Subscription:
        """Создание новой подписки."""
        import uuid
        
        subscription_id = str(uuid.uuid4())
        now = datetime.now()
        
        # Рассчитываем дату окончания пробного периода
        trial_ends_at = None
        if trial_days > 0:
            trial_ends_at = now + timedelta(days=trial_days)
            status = SubscriptionStatus.TRIAL
        else:
            status = SubscriptionStatus.ACTIVE
        
        # Рассчитываем дату окончания периода
        if billing_cycle == BillingCycle.MONTHLY:
            period_end = now + timedelta(days=30)
        elif billing_cycle == BillingCycle.QUARTERLY:
            period_end = now + timedelta(days=90)
        elif billing_cycle == BillingCycle.YEARLY:
            period_end = now + timedelta(days=365)
        else:  # LIFETIME
            period_end = now + timedelta(days=36500)  # 100 лет
        
        subscription = Subscription(
            id=subscription_id,
            user_id=user_id,
            plan_id=plan_id,
            status=status,
            billing_cycle=billing_cycle,
            started_at=now,
            current_period_end=period_end,
            trial_ends_at=trial_ends_at
        )
        
        self._save_subscription(subscription)
        return subscription
    
    def cancel_subscription(self, subscription_id: str) -> bool:
        """Отмена подписки."""
        subscription = self.get_subscription(subscription_id)
        if not subscription or subscription.status != SubscriptionStatus.ACTIVE:
            return False
        
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = datetime.now()
        
        self._save_subscription(subscription)
        return True
    
    def renew_subscription(self, subscription_id: str) -> bool:
        """Продление подписки."""
        subscription = self.get_subscription(subscription_id)
        if not subscription or subscription.status != SubscriptionStatus.ACTIVE:
            return False
        
        # Продлеваем период
        current_end = subscription.current_period_end
        if subscription.billing_cycle == BillingCycle.MONTHLY:
            new_end = current_end + timedelta(days=30)
        elif subscription.billing_cycle == BillingCycle.QUARTERLY:
            new_end = current_end + timedelta(days=90)
        elif subscription.billing_cycle == BillingCycle.YEARLY:
            new_end = current_end + timedelta(days=365)
        else:
            return True  # Lifetime не нужно продлевать
        
        subscription.current_period_end = new_end
        self._save_subscription(subscription)
        
        return True
    
    def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        """Получение подписки."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM subscriptions WHERE id = ?",
                (subscription_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return self._row_to_subscription(row)
        return None
    
    def get_user_subscriptions(self, user_id: str) -> List[Subscription]:
        """Получение подписок пользователя."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY started_at DESC",
                (user_id,)
            )
            
            subscriptions = []
            for row in cursor.fetchall():
                subscriptions.append(self._row_to_subscription(row))
            
            return subscriptions
    
    def _save_subscription(self, subscription: Subscription):
        """Сохранение подписки."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO subscriptions VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                subscription.id,
                subscription.user_id,
                subscription.plan_id,
                subscription.status.value,
                subscription.billing_cycle.value,
                subscription.started_at.isoformat(),
                subscription.current_period_end.isoformat(),
                subscription.cancelled_at.isoformat() if subscription.cancelled_at else None,
                subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else None
            ))
            conn.commit()
    
    def _row_to_subscription(self, row) -> Subscription:
        """Преобразование строки БД в Subscription."""
        return Subscription(
            id=row['id'],
            user_id=row['user_id'],
            plan_id=row['plan_id'],
            status=SubscriptionStatus(row['status']),
            billing_cycle=BillingCycle(row['billing_cycle']),
            started_at=datetime.fromisoformat(row['started_at']),
            current_period_end=datetime.fromisoformat(row['current_period_end']),
            cancelled_at=datetime.fromisoformat(row['cancelled_at']) if row['cancelled_at'] else None,
            trial_ends_at=datetime.fromisoformat(row['trial_ends_at']) if row['trial_ends_at'] else None
        )