import asyncio
import smtplib
import json
import logging
from typing import Any, Dict, List, Optional, Union, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import sqlite3
from contextlib import contextmanager
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from abc import ABC, abstractmethod
import uuid
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    """Типы уведомлений."""
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"
    SLACK = "slack"
    TELEGRAM = "telegram"
    IN_APP = "in_app"


class NotificationPriority(str, Enum):
    """Приоритеты уведомлений."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(str, Enum):
    """Статусы уведомлений."""
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"
    ARCHIVED = "archived"


@dataclass
class NotificationTemplate:
    """Шаблон уведомления."""
    id: str
    name: str
    notification_type: NotificationType
    subject: Optional[str] = None
    body: str = ""
    body_html: Optional[str] = None
    variables: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    
    def render(self, context: Dict[str, Any]) -> Dict[str, str]:
        """
        Рендеринг шаблона с контекстом.
        
        Args:
            context: Контекст для подстановки переменных
            
        Returns:
            Словарь с отрендеренным subject и body
        """
        rendered_subject = self.subject
        rendered_body = self.body
        rendered_body_html = self.body_html
        
        # Заменяем переменные в формате {{variable}}
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"
            
            if rendered_subject:
                rendered_subject = rendered_subject.replace(placeholder, str(value))
            
            if rendered_body:
                rendered_body = rendered_body.replace(placeholder, str(value))
            
            if rendered_body_html:
                rendered_body_html = rendered_body_html.replace(placeholder, str(value))
        
        result = {
            'body': rendered_body,
            'body_html': rendered_body_html
        }
        
        if rendered_subject:
            result['subject'] = rendered_subject
        
        return result


@dataclass
class Notification:
    """Уведомление."""
    id: str
    user_id: str
    notification_type: NotificationType
    recipient: str  # email, phone number, device token, etc.
    subject: Optional[str] = None
    body: str = ""
    body_html: Optional[str] = None
    priority: NotificationPriority = NotificationPriority.NORMAL
    status: NotificationStatus = NotificationStatus.PENDING
    metadata: Dict[str, Any] = field(default_factory=dict)
    template_id: Optional[str] = None
    template_variables: Dict[str, Any] = field(default_factory=dict)
    scheduled_for: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'notification_type': self.notification_type.value,
            'recipient': self.recipient,
            'subject': self.subject,
            'body': self.body,
            'body_html': self.body_html,
            'priority': self.priority.value,
            'status': self.status.value,
            'metadata': self.metadata,
            'template_id': self.template_id,
            'template_variables': self.template_variables,
            'scheduled_for': self.scheduled_for.isoformat() if self.scheduled_for else None,
            'created_at': self.created_at.isoformat(),
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'error_message': self.error_message
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Notification':
        """Десериализация из словаря."""
        return cls(
            id=data['id'],
            user_id=data['user_id'],
            notification_type=NotificationType(data['notification_type']),
            recipient=data['recipient'],
            subject=data.get('subject'),
            body=data.get('body', ''),
            body_html=data.get('body_html'),
            priority=NotificationPriority(data.get('priority', 'normal')),
            status=NotificationStatus(data.get('status', 'pending')),
            metadata=data.get('metadata', {}),
            template_id=data.get('template_id'),
            template_variables=data.get('template_variables', {}),
            scheduled_for=datetime.fromisoformat(data['scheduled_for']) if data.get('scheduled_for') else None,
            created_at=datetime.fromisoformat(data['created_at']),
            sent_at=datetime.fromisoformat(data['sent_at']) if data.get('sent_at') else None,
            read_at=datetime.fromisoformat(data['read_at']) if data.get('read_at') else None,
            retry_count=data.get('retry_count', 0),
            max_retries=data.get('max_retries', 3),
            error_message=data.get('error_message')
        )


class NotificationValidator:
    """Валидатор уведомлений."""
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Валидация email адреса."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Валидация номера телефона."""
        # Простая валидация - только цифры, от 10 до 15 символов
        pattern = r'^\+?[0-9]{10,15}$'
        return re.match(pattern, phone) is not None
    
    @staticmethod
    def validate_notification(notification: Notification) -> Tuple[bool, List[str]]:
        """
        Валидация уведомления.
        
        Args:
            notification: Уведомление для валидации
            
        Returns:
            (валидно, список ошибок)
        """
        errors = []
        
        # Проверка получателя
        if notification.notification_type == NotificationType.EMAIL:
            if not NotificationValidator.validate_email(notification.recipient):
                errors.append(f"Invalid email address: {notification.recipient}")
        
        elif notification.notification_type == NotificationType.SMS:
            if not NotificationValidator.validate_phone(notification.recipient):
                errors.append(f"Invalid phone number: {notification.recipient}")
        
        # Проверка тела уведомления
        if not notification.body and not notification.body_html:
            errors.append("Notification body is empty")
        
        # Проверка максимальной длины
        if len(notification.body) > 10000:
            errors.append("Notification body is too long (max 10000 characters)")
        
        if notification.body_html and len(notification.body_html) > 50000:
            errors.append("HTML body is too long (max 50000 characters)")
        
        # Проверка приоритета
        if notification.priority not in list(NotificationPriority):
            errors.append(f"Invalid priority: {notification.priority}")
        
        return len(errors) == 0, errors


class NotificationStorage:
    """Хранилище уведомлений."""
    
    def __init__(self, db_path: str = "notifications.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица шаблонов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notification_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    notification_type TEXT NOT NULL,
                    subject TEXT,
                    body TEXT NOT NULL,
                    body_html TEXT,
                    variables TEXT,  -- JSON массив
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            
            # Таблица уведомлений
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    notification_type TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT,
                    body TEXT NOT NULL,
                    body_html TEXT,
                    priority TEXT DEFAULT 'normal',
                    status TEXT DEFAULT 'pending',
                    metadata TEXT,  -- JSON объект
                    template_id TEXT,
                    template_variables TEXT,  -- JSON объект
                    scheduled_for TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_at TIMESTAMP,
                    read_at TIMESTAMP,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    error_message TEXT,
                    FOREIGN KEY (template_id) REFERENCES notification_templates(id)
                )
            """)
            
            # Таблица пользовательских настроек
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_notification_settings (
                    user_id TEXT PRIMARY KEY,
                    email_enabled BOOLEAN DEFAULT TRUE,
                    sms_enabled BOOLEAN DEFAULT TRUE,
                    push_enabled BOOLEAN DEFAULT TRUE,
                    webhook_enabled BOOLEAN DEFAULT TRUE,
                    quiet_hours_start TIME,
                    quiet_hours_end TIME,
                    language TEXT DEFAULT 'en',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status, scheduled_for)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(notification_type, status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_scheduled ON notifications(scheduled_for)")
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для подключения к БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def save_template(self, template: NotificationTemplate) -> bool:
        """Сохранение шаблона."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO notification_templates 
                    (id, name, notification_type, subject, body, body_html, 
                     variables, updated_at, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    template.id,
                    template.name,
                    template.notification_type.value,
                    template.subject,
                    template.body,
                    template.body_html,
                    json.dumps(template.variables),
                    datetime.now(),
                    template.is_active
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving template {template.id}: {e}")
            return False
    
    def get_template(self, template_id: str) -> Optional[NotificationTemplate]:
        """Получение шаблона по ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM notification_templates WHERE id = ?",
                    (template_id,)
                )
                
                row = cursor.fetchone()
                if row:
                    return NotificationTemplate(
                        id=row['id'],
                        name=row['name'],
                        notification_type=NotificationType(row['notification_type']),
                        subject=row['subject'],
                        body=row['body'],
                        body_html=row['body_html'],
                        variables=json.loads(row['variables']) if row['variables'] else [],
                        created_at=datetime.fromisoformat(row['created_at']),
                        updated_at=datetime.fromisoformat(row['updated_at']),
                        is_active=bool(row['is_active'])
                    )
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting template {template_id}: {e}")
            return None
    
    def get_template_by_name(self, name: str) -> Optional[NotificationTemplate]:
        """Получение шаблона по имени."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM notification_templates WHERE name = ? AND is_active = TRUE",
                    (name,)
                )
                
                row = cursor.fetchone()
                if row:
                    return NotificationTemplate(
                        id=row['id'],
                        name=row['name'],
                        notification_type=NotificationType(row['notification_type']),
                        subject=row['subject'],
                        body=row['body'],
                        body_html=row['body_html'],
                        variables=json.loads(row['variables']) if row['variables'] else [],
                        created_at=datetime.fromisoformat(row['created_at']),
                        updated_at=datetime.fromisoformat(row['updated_at']),
                        is_active=bool(row['is_active'])
                    )
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting template {name}: {e}")
            return None
    
    def save_notification(self, notification: Notification) -> bool:
        """Сохранение уведомления."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO notifications 
                    (id, user_id, notification_type, recipient, subject, body, body_html,
                     priority, status, metadata, template_id, template_variables,
                     scheduled_for, created_at, sent_at, read_at, retry_count,
                     max_retries, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    notification.id,
                    notification.user_id,
                    notification.notification_type.value,
                    notification.recipient,
                    notification.subject,
                    notification.body,
                    notification.body_html,
                    notification.priority.value,
                    notification.status.value,
                    json.dumps(notification.metadata) if notification.metadata else None,
                    notification.template_id,
                    json.dumps(notification.template_variables) if notification.template_variables else None,
                    notification.scheduled_for,
                    notification.created_at,
                    notification.sent_at,
                    notification.read_at,
                    notification.retry_count,
                    notification.max_retries,
                    notification.error_message
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving notification {notification.id}: {e}")
            return False
    
    def update_notification_status(
        self,
        notification_id: str,
        status: NotificationStatus,
        error_message: Optional[str] = None,
        sent_at: Optional[datetime] = None
    ) -> bool:
        """Обновление статуса уведомления."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                updates = {
                    'status': status.value,
                    'error_message': error_message,
                    'retry_count': f"retry_count + {1 if status == NotificationStatus.FAILED else 0}"
                }
                
                if sent_at:
                    updates['sent_at'] = sent_at
                
                if status == NotificationStatus.FAILED:
                    updates['retry_count'] = 'retry_count + 1'
                
                # Собираем SQL запрос
                set_clause = ', '.join([
                    f"{k} = {v}" if 'retry_count' in k else f"{k} = ?"
                    for k, v in updates.items()
                ])
                
                params = [v for k, v in updates.items() if k != 'retry_count']
                params.append(notification_id)
                
                cursor.execute(
                    f"UPDATE notifications SET {set_clause} WHERE id = ?",
                    params
                )
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error updating notification {notification_id}: {e}")
            return False
    
    def get_pending_notifications(self, limit: int = 100) -> List[Notification]:
        """Получение pending уведомлений."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM notifications 
                    WHERE status = 'pending' 
                    AND (scheduled_for IS NULL OR scheduled_for <= ?)
                    ORDER BY 
                        CASE priority
                            WHEN 'urgent' THEN 1
                            WHEN 'high' THEN 2
                            WHEN 'normal' THEN 3
                            WHEN 'low' THEN 4
                        END,
                        created_at ASC
                    LIMIT ?
                """, (datetime.now(), limit))
                
                notifications = []
                for row in cursor.fetchall():
                    notifications.append(self._row_to_notification(row))
                
                return notifications
                
        except Exception as e:
            logger.error(f"Error getting pending notifications: {e}")
            return []
    
    def get_user_notifications(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[NotificationStatus] = None,
        notification_type: Optional[NotificationType] = None
    ) -> List[Notification]:
        """Получение уведомлений пользователя."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM notifications WHERE user_id = ?"
                params = [user_id]
                
                if status_filter:
                    query += " AND status = ?"
                    params.append(status_filter.value)
                
                if notification_type:
                    query += " AND notification_type = ?"
                    params.append(notification_type.value)
                
                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                
                cursor.execute(query, params)
                
                notifications = []
                for row in cursor.fetchall():
                    notifications.append(self._row_to_notification(row))
                
                return notifications
                
        except Exception as e:
            logger.error(f"Error getting user notifications: {e}")
            return []
    
    def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        """Отметка уведомления как прочитанного."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE notifications 
                    SET status = 'read', read_at = ? 
                    WHERE id = ? AND user_id = ?
                """, (datetime.now(), notification_id, user_id))
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error marking notification as read: {e}")
            return False
    
    def get_notification_stats(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Получение статистики уведомлений."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        notification_type,
                        status,
                        COUNT(*) as count
                    FROM notifications 
                    WHERE created_at BETWEEN ? AND ?
                    GROUP BY notification_type, status
                """, (start_date, end_date))
                
                stats = {
                    'total': 0,
                    'by_type': {},
                    'by_status': {},
                    'success_rate': 0.0
                }
                
                total_sent = 0
                total_delivered = 0
                
                for row in cursor.fetchall():
                    n_type = row['notification_type']
                    status = row['status']
                    count = row['count']
                    
                    stats['total'] += count
                    
                    # Статистика по типам
                    if n_type not in stats['by_type']:
                        stats['by_type'][n_type] = 0
                    stats['by_type'][n_type] += count
                    
                    # Статистика по статусам
                    if status not in stats['by_status']:
                        stats['by_status'][status] = 0
                    stats['by_status'][status] += count
                    
                    # Для расчета success rate
                    if status in ['sent', 'delivered', 'read']:
                        total_delivered += count
                    if status != 'pending':
                        total_sent += count
                
                # Расчет success rate
                if total_sent > 0:
                    stats['success_rate'] = (total_delivered / total_sent) * 100
                
                return stats
                
        except Exception as e:
            logger.error(f"Error getting notification stats: {e}")
            return {}
    
    def _row_to_notification(self, row) -> Notification:
        """Преобразование строки БД в объект Notification."""
        return Notification(
            id=row['id'],
            user_id=row['user_id'],
            notification_type=NotificationType(row['notification_type']),
            recipient=row['recipient'],
            subject=row['subject'],
            body=row['body'],
            body_html=row['body_html'],
            priority=NotificationPriority(row['priority']),
            status=NotificationStatus(row['status']),
            metadata=json.loads(row['metadata']) if row['metadata'] else {},
            template_id=row['template_id'],
            template_variables=json.loads(row['template_variables']) if row['template_variables'] else {},
            scheduled_for=datetime.fromisoformat(row['scheduled_for']) if row['scheduled_for'] else None,
            created_at=datetime.fromisoformat(row['created_at']),
            sent_at=datetime.fromisoformat(row['sent_at']) if row['sent_at'] else None,
            read_at=datetime.fromisoformat(row['read_at']) if row['read_at'] else None,
            retry_count=row['retry_count'],
            max_retries=row['max_retries'],
            error_message=row['error_message']
        )


class NotificationChannel(ABC):
    """Абстрактный класс канала уведомлений."""
    
    @abstractmethod
    async def send(self, notification: Notification) -> bool:
        """
        Отправка уведомления.
        
        Args:
            notification: Уведомление для отправки
            
        Returns:
            True если успешно отправлено
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Получение имени канала."""
        pass


class EmailChannel(NotificationChannel):
    """Канал для отправки email."""
    
    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 587,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        use_tls: bool = True,
        from_email: str = "noreply@example.com"
    ):
        """
        Инициализация email канала.
        
        Args:
            smtp_host: SMTP хост
            smtp_port: SMTP порт
            smtp_username: Имя пользователя SMTP
            smtp_password: Пароль SMTP
            use_tls: Использовать TLS
            from_email: Email отправителя
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.use_tls = use_tls
        self.from_email = from_email
    
    def get_name(self) -> str:
        return "email"
    
    async def send(self, notification: Notification) -> bool:
        """Отправка email."""
        try:
            # Создаем сообщение
            msg = MIMEMultipart('alternative')
            msg['Subject'] = notification.subject or "Notification"
            msg['From'] = self.from_email
            msg['To'] = notification.recipient
            
            # Текстовая часть
            if notification.body:
                text_part = MIMEText(notification.body, 'plain', 'utf-8')
                msg.attach(text_part)
            
            # HTML часть
            if notification.body_html:
                html_part = MIMEText(notification.body_html, 'html', 'utf-8')
                msg.attach(html_part)
            
            # Отправка
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._send_sync,
                msg
            )
            
            logger.info(f"Email sent to {notification.recipient}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {notification.recipient}: {e}")
            return False
    
    def _send_sync(self, msg: MIMEMultipart):
        """Синхронная отправка email."""
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                
                if self.smtp_username and self.smtp_password:
                    server.login(self.smtp_username, self.smtp_password)
                
                server.send_message(msg)
        except Exception as e:
            raise e


class WebhookChannel(NotificationChannel):
    """Канал для отправки webhook уведомлений."""
    
    def __init__(self, timeout: int = 10):
        """
        Инициализация webhook канала.
        
        Args:
            timeout: Таймаут запроса
        """
        self.timeout = timeout
        self.session = requests.Session()
    
    def get_name(self) -> str:
        return "webhook"
    
    async def send(self, notification: Notification) -> bool:
        """Отправка webhook."""
        try:
            # Получаем URL из metadata или recipient
            webhook_url = notification.metadata.get('webhook_url', notification.recipient)
            
            # Подготовка данных
            payload = {
                'notification_id': notification.id,
                'user_id': notification.user_id,
                'type': notification.notification_type.value,
                'subject': notification.subject,
                'body': notification.body,
                'metadata': notification.metadata,
                'timestamp': datetime.now().isoformat()
            }
            
            # Headers
            headers = notification.metadata.get('headers', {})
            headers.setdefault('Content-Type', 'application/json')
            headers.setdefault('User-Agent', 'NotificationSystem/1.0')
            
            # Отправка
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.session.post(
                    webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout
                )
            )
            
            if response.status_code >= 200 and response.status_code < 300:
                logger.info(f"Webhook sent to {webhook_url}, status: {response.status_code}")
                return True
            else:
                logger.warning(f"Webhook to {webhook_url} failed with status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")
            return False


class SlackChannel(NotificationChannel):
    """Канал для отправки в Slack."""
    
    def __init__(self, default_webhook_url: Optional[str] = None):
        """
        Инициализация Slack канала.
        
        Args:
            default_webhook_url: URL вебхука Slack по умолчанию
        """
        self.default_webhook_url = default_webhook_url
    
    def get_name(self) -> str:
        return "slack"
    
    async def send(self, notification: Notification) -> bool:
        """Отправка в Slack."""
        try:
            # Получаем webhook URL
            webhook_url = notification.metadata.get(
                'slack_webhook_url', 
                self.default_webhook_url
            )
            
            if not webhook_url:
                raise ValueError("Slack webhook URL not provided")
            
            # Подготовка сообщения Slack
            slack_message = {
                'text': notification.subject or "Notification",
                'blocks': []
            }
            
            # Добавляем блоки если есть тело
            if notification.body:
                slack_message['blocks'].append({
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': notification.body
                    }
                })
            
            # Добавляем метаданные если есть
            if notification.metadata.get('slack_blocks'):
                slack_message['blocks'].extend(notification.metadata['slack_blocks'])
            
            # Отправка
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    webhook_url,
                    json=slack_message,
                    timeout=10
                )
            )
            
            if response.status_code == 200 and response.json().get('ok'):
                logger.info(f"Slack message sent via {webhook_url}")
                return True
            else:
                logger.warning(f"Slack webhook failed: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send Slack message: {e}")
            return False


class NotificationSender:
    """Отправитель уведомлений."""
    
    def __init__(self, storage: NotificationStorage):
        """
        Инициализация отправителя.
        
        Args:
            storage: Хранилище уведомлений
        """
        self.storage = storage
        self.channels: Dict[NotificationType, NotificationChannel] = {}
        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.check_interval = 5  # секунды
    
    def register_channel(self, channel: NotificationChannel) -> None:
        """
        Регистрация канала уведомлений.
        
        Args:
            channel: Канал для регистрации
        """
        # Определяем тип канала по имени
        channel_name = channel.get_name()
        type_map = {
            'email': NotificationType.EMAIL,
            'webhook': NotificationType.WEBHOOK,
            'slack': NotificationType.SLACK,
            'sms': NotificationType.SMS,
            'push': NotificationType.PUSH,
            'telegram': NotificationType.TELEGRAM
        }
        
        if channel_name in type_map:
            self.channels[type_map[channel_name]] = channel
            logger.info(f"Registered channel: {channel_name}")
        else:
            logger.warning(f"Unknown channel type: {channel_name}")
    
    async def send_notification(self, notification: Notification) -> bool:
        """
        Отправка одного уведомления.
        
        Args:
            notification: Уведомление для отправки
            
        Returns:
            True если успешно отправлено
        """
        # Валидация
        is_valid, errors = NotificationValidator.validate_notification(notification)
        if not is_valid:
            logger.error(f"Notification {notification.id} validation failed: {errors}")
            self.storage.update_notification_status(
                notification.id,
                NotificationStatus.FAILED,
                f"Validation failed: {', '.join(errors)}"
            )
            return False
        
        # Получаем канал
        channel = self.channels.get(notification.notification_type)
        if not channel:
            logger.error(f"No channel registered for type: {notification.notification_type}")
            self.storage.update_notification_status(
                notification.id,
                NotificationStatus.FAILED,
                f"No channel for type: {notification.notification_type}"
            )
            return False
        
        try:
            # Обновляем статус на sending
            self.storage.update_notification_status(
                notification.id,
                NotificationStatus.SENDING
            )
            
            # Отправка
            success = await channel.send(notification)
            
            if success:
                self.storage.update_notification_status(
                    notification.id,
                    NotificationStatus.SENT,
                    sent_at=datetime.now()
                )
                logger.info(f"Notification {notification.id} sent successfully")
            else:
                self.storage.update_notification_status(
                    notification.id,
                    NotificationStatus.FAILED,
                    "Channel send failed"
                )
                logger.warning(f"Notification {notification.id} send failed")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending notification {notification.id}: {e}")
            self.storage.update_notification_status(
                notification.id,
                NotificationStatus.FAILED,
                str(e)
            )
            return False
    
    def _worker_loop(self):
        """Цикл обработки уведомлений."""
        logger.info("Notification sender worker started")
        
        while self.running:
            try:
                # Получаем pending уведомления
                pending_notifications = self.storage.get_pending_notifications(limit=10)
                
                if pending_notifications:
                    # Создаем event loop для асинхронной обработки
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    # Отправляем каждое уведомление
                    tasks = []
                    for notification in pending_notifications:
                        tasks.append(self.send_notification(notification))
                    
                    # Запускаем все задачи параллельно
                    if tasks:
                        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                    
                    loop.close()
                
                # Пауза перед следующей проверкой
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in notification worker: {e}")
                time.sleep(10)
    
    def start(self):
        """Запуск отправителя."""
        if self.running:
            logger.warning("Notification sender is already running")
            return
        
        self.running = True
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            name="NotificationSenderWorker",
            daemon=True
        )
        self.worker_thread.start()
        
        logger.info("Notification sender started")
    
    def stop(self):
        """Остановка отправителя."""
        self.running = False
        
        if self.worker_thread:
            self.worker_thread.join(timeout=10)
        
        logger.info("Notification sender stopped")


class NotificationService:
    """Сервис уведомлений."""
    
    def __init__(self, storage: Optional[NotificationStorage] = None):
        """
        Инициализация сервиса уведомлений.
        
        Args:
            storage: Хранилище уведомлений
        """
        self.storage = storage or NotificationStorage()
        self.sender = NotificationSender(self.storage)
        self.validator = NotificationValidator()
        
        # Регистрация каналов по умолчанию
        self._register_default_channels()
    
    def _register_default_channels(self):
        """Регистрация каналов по умолчанию."""
        # Email канал (конфигурация из env в реальном приложении)
        email_channel = EmailChannel(
            smtp_host="localhost",
            smtp_port=587,
            from_email="notifications@example.com"
        )
        self.sender.register_channel(email_channel)
        
        # Webhook канал
        webhook_channel = WebhookChannel(timeout=10)
        self.sender.register_channel(webhook_channel)
        
        # Slack канал
        slack_channel = SlackChannel()
        self.sender.register_channel(slack_channel)
    
    def create_notification(
        self,
        user_id: str,
        notification_type: NotificationType,
        recipient: str,
        subject: Optional[str] = None,
        body: str = "",
        body_html: Optional[str] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
        template_name: Optional[str] = None,
        template_variables: Optional[Dict[str, Any]] = None,
        scheduled_for: Optional[datetime] = None
    ) -> Optional[Notification]:
        """
        Создание уведомления.
        
        Args:
            user_id: ID пользователя
            notification_type: Тип уведомления
            recipient: Получатель
            subject: Заголовок
            body: Текст уведомления
            body_html: HTML версия
            priority: Приоритет
            metadata: Метаданные
            template_name: Имя шаблона
            template_variables: Переменные для шаблона
            scheduled_for: Время отправки
            
        Returns:
            Созданное уведомление или None при ошибке
        """
        # Если указан шаблон, рендерим его
        if template_name:
            template = self.storage.get_template_by_name(template_name)
            if not template:
                logger.error(f"Template not found: {template_name}")
                return None
            
            # Проверяем тип уведомления
            if template.notification_type != notification_type:
                logger.error(f"Template type mismatch: {template.notification_type} != {notification_type}")
                return None
            
            # Рендерим шаблон
            rendered = template.render(template_variables or {})
            
            # Используем отрендеренные значения
            subject = rendered.get('subject', subject)
            body = rendered.get('body', body)
            body_html = rendered.get('body_html', body_html)
            
            template_id = template.id
        else:
            template_id = None
        
        # Создаем уведомление
        notification = Notification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            notification_type=notification_type,
            recipient=recipient,
            subject=subject,
            body=body,
            body_html=body_html,
            priority=priority,
            metadata=metadata or {},
            template_id=template_id,
            template_variables=template_variables or {},
            scheduled_for=scheduled_for
        )
        
        # Валидация
        is_valid, errors = self.validator.validate_notification(notification)
        if not is_valid:
            logger.error(f"Notification validation failed: {errors}")
            return None
        
        # Сохраняем
        success = self.storage.save_notification(notification)
        if success:
            logger.info(f"Notification created: {notification.id}")
            return notification
        else:
            logger.error(f"Failed to save notification: {notification.id}")
            return None
    
    def send_immediate(
        self,
        user_id: str,
        notification_type: NotificationType,
        recipient: str,
        subject: str,
        body: str,
        **kwargs
    ) -> Optional[str]:
        """
        Создание и немедленная отправка уведомления.
        
        Args:
            user_id: ID пользователя
            notification_type: Тип уведомления
            recipient: Получатель
            subject: Заголовок
            body: Текст
            **kwargs: Дополнительные параметры
            
        Returns:
            ID уведомления или None
        """
        notification = self.create_notification(
            user_id=user_id,
            notification_type=notification_type,
            recipient=recipient,
            subject=subject,
            body=body,
            **kwargs
        )
        
        if notification:
            # Немедленная отправка (в реальном приложении через очередь)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(self.sender.send_notification(notification))
            loop.close()
            
            if success:
                return notification.id
        
        return None
    
    def create_template(
        self,
        name: str,
        notification_type: NotificationType,
        body: str,
        subject: Optional[str] = None,
        body_html: Optional[str] = None,
        variables: Optional[List[str]] = None
    ) -> Optional[NotificationTemplate]:
        """
        Создание шаблона уведомления.
        
        Args:
            name: Имя шаблона
            notification_type: Тип уведомления
            body: Текст шаблона
            subject: Заголовок
            body_html: HTML версия
            variables: Список переменных
            
        Returns:
            Созданный шаблон или None
        """
        template = NotificationTemplate(
            id=str(uuid.uuid4()),
            name=name,
            notification_type=notification_type,
            subject=subject,
            body=body,
            body_html=body_html,
            variables=variables or []
        )
        
        success = self.storage.save_template(template)
        if success:
            logger.info(f"Template created: {name}")
            return template
        else:
            logger.error(f"Failed to create template: {name}")
            return None
    
    def get_user_notifications(
        self,
        user_id: str,
        limit: int = 50,
        unread_only: bool = False
    ) -> List[Notification]:
        """
        Получение уведомлений пользователя.
        
        Args:
            user_id: ID пользователя
            limit: Максимальное количество
            unread_only: Только непрочитанные
            
        Returns:
            Список уведомлений
        """
        status_filter = NotificationStatus.READ if not unread_only else None
        return self.storage.get_user_notifications(
            user_id=user_id,
            limit=limit,
            status_filter=status_filter
        )
    
    def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        """
        Отметка уведомления как прочитанного.
        
        Args:
            notification_id: ID уведомления
            user_id: ID пользователя
            
        Returns:
            True если успешно
        """
        return self.storage.mark_as_read(notification_id, user_id)
    
    def get_stats(
        self,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Получение статистики уведомлений.
        
        Args:
            days: Количество дней для анализа
            
        Returns:
            Статистика
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        return self.storage.get_notification_stats(start_date, end_date)
    
    def start_service(self):
        """Запуск сервиса уведомлений."""
        self.sender.start()
        logger.info("Notification service started")
    
    def stop_service(self):
        """Остановка сервиса уведомлений."""
        self.sender.stop()
        logger.info("Notification service stopped")


# --- Пример использования ---
def main():
    """Демонстрация работы системы уведомлений."""
    print("=== Notification System Demo ===")
    
    # Создаем сервис уведомлений
    service = NotificationService()
    
    try:
        # Создаем шаблоны
        print("\n1. Creating notification templates...")
        
        # Шаблон для welcome email
        welcome_template = service.create_template(
            name="welcome_email",
            notification_type=NotificationType.EMAIL,
            subject="Welcome to Our Service, {{name}}!",
            body="""Hello {{name}},

Welcome to our platform! We're excited to have you on board.

Your account details:
- Username: {{username}}
- Email: {{email}}

Best regards,
The Team""",
            body_html="""<h1>Welcome {{name}}!</h1>
<p>Welcome to our platform! We're excited to have you on board.</p>
<p><strong>Your account details:</strong></p>
<ul>
<li><strong>Username:</strong> {{username}}</li>
<li><strong>Email:</strong> {{email}}</