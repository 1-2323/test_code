import time
import requests
import smtplib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import json
from datetime import datetime
import threading


class NotificationType(Enum):
    """Типы уведомлений"""
    EMAIL = "email"
    SLACK = "slack"
    TELEGRAM = "telegram"


@dataclass
class ServiceNode:
    """Модель узла для мониторинга"""
    name: str
    url: str
    check_interval: int = 60  # секунды
    timeout: int = 5  # секунды
    expected_status: int = 200


@dataclass
class NotificationConfig:
    """Конфигурация уведомлений"""
    type: NotificationType
    webhook_url: Optional[str] = None  # Для Slack/Telegram
    email_config: Optional[Dict[str, Any]] = None  # Для email
    enabled: bool = True


class ServiceMonitor:
    """
    Система мониторинга доступности критических узлов.
    """
    
    def __init__(
        self,
        nodes: List[ServiceNode],
        notification_config: NotificationConfig,
        retry_count: int = 3
    ):
        """
        Инициализация монитора.
        
        Args:
            nodes: Список узлов для мониторинга
            notification_config: Конфигурация уведомлений
            retry_count: Количество попыток перед отправкой уведомления
        """
        self.nodes = nodes
        self.notification_config = notification_config
        self.retry_count = retry_count
        self.failure_counters: Dict[str, int] = {}
        self.is_running = False
        
        print(f"Мониторинг инициализирован для {len(nodes)} узлов")
    
    def _check_node(self, node: ServiceNode) -> bool:
        """
        Проверяет доступность узла.
        
        Args:
            node: Узел для проверки
            
        Returns:
            True если узел доступен, иначе False
        """
        try:
            response = requests.get(
                node.url, 
                timeout=node.timeout,
                headers={'User-Agent': 'ServiceMonitor/1.0'}
            )
            
            if response.status_code == node.expected_status:
                print(f"✓ {node.name} доступен (статус: {response.status_code})")
                return True
            else:
                print(f"✗ {node.name} недоступен (статус: {response.status_code})")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"✗ {node.name} ошибка соединения: {str(e)}")
            return False
    
    def _send_email_notification(
        self, 
        subject: str, 
        message: str
    ) -> None:
        """
        Отправляет уведомление по email.
        
        Args:
            subject: Тема письма
            message: Текст сообщения
        """
        if not self.notification_config.email_config:
            print("Конфигурация email не настроена")
            return
        
        config = self.notification_config.email_config
        
        try:
            # Создаем SMTP соединение
            with smtplib.SMTP(config['smtp_server'], config['smtp_port']) as server:
                server.starttls()
                server.login(config['username'], config['password'])
                
                email_message = (
                    f"From: {config['from_email']}\n"
                    f"To: {config['to_email']}\n"
                    f"Subject: {subject}\n\n"
                    f"{message}"
                )
                
                server.sendmail(
                    config['from_email'],
                    config['to_email'],
                    email_message.encode('utf-8')
                )
                
            print(f"Уведомление отправлено по email на {config['to_email']}")
            
        except Exception as e:
            print(f"Ошибка отправки email: {str(e)}")
    
    def _send_slack_notification(self, message: str) -> None:
        """
        Отправляет уведомление в Slack.
        
        Args:
            message: Текст сообщения
        """
        if not self.notification_config.webhook_url:
            print("Webhook URL для Slack не настроен")
            return
        
        try:
            payload = {
                "text": message,
                "username": "Service Monitor",
                "icon_emoji": ":warning:"
            }
            
            response = requests.post(
                self.notification_config.webhook_url,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                print("Уведомление отправлено в Slack")
            else:
                print(f"Ошибка отправки в Slack: {response.status_code}")
                
        except Exception as e:
            print(f"Ошибка отправки Slack уведомления: {str(e)}")
    
    def _send_telegram_notification(self, message: str) -> None:
        """
        Отправляет уведомление в Telegram.
        
        Args:
            message: Текст сообщения
        """
        if not self.notification_config.webhook_url:
            print("Webhook URL для Telegram не настроен")
            return
        
        try:
            # Для Telegram используется Bot API
            payload = {
                "chat_id": self.notification_config.webhook_url.split('/')[-1],
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(
                f"https://api.telegram.org/bot{self.notification_config.webhook_url}/sendMessage",
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                print("Уведомление отправлено в Telegram")
            else:
                print(f"Ошибка отправки в Telegram: {response.status_code}")
                
        except Exception as e:
            print(f"Ошибка отправки Telegram уведомления: {str(e)}")
    
    def _send_notification(self, node: ServiceNode, error_message: str) -> None:
        """
        Отправляет уведомление о сбое.
        
        Args:
            node: Узел, на котором произошел сбой
            error_message: Описание ошибки
        """
        if not self.notification_config.enabled:
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = (
            f"🚨 Сбой сервиса!\n"
            f"Время: {timestamp}\n"
            f"Сервис: {node.name}\n"
            f"URL: {node.url}\n"
            f"Ошибка: {error_message}\n"
            f"Попыток восстановления: {self.failure_counters.get(node.name, 0)}"
        )
        
        notification_type = self.notification_config.type
        
        if notification_type == NotificationType.EMAIL:
            self._send_email_notification(
                subject=f"Сбой сервиса: {node.name}",
                message=message
            )
        elif notification_type == NotificationType.SLACK:
            self._send_slack_notification(message)
        elif notification_type == NotificationType.TELEGRAM:
            self._send_telegram_notification(message)
    
    def _monitor_node(self, node: ServiceNode) -> None:
        """
        Мониторит один узел в отдельном потоке.
        
        Args:
            node: Узел для мониторинга
        """
        print(f"Запущен мониторинг узла: {node.name}")
        
        while self.is_running:
            try:
                is_available = self._check_node(node)
                
                if not is_available:
                    # Увеличиваем счетчик сбоев
                    self.failure_counters[node.name] = \
                        self.failure_counters.get(node.name, 0) + 1
                    
                    # Если достигли порога сбоев - отправляем уведомление
                    if self.failure_counters[node.name] >= self.retry_count:
                        self._send_notification(
                            node=node,
                            error_message="Сервис недоступен"
                        )
                        # Сбрасываем счетчик после отправки уведомления
                        self.failure_counters[node.name] = 0
                else:
                    # Сбрасываем счетчик сбоев при успешной проверке
                    if node.name in self.failure_counters:
                        del self.failure_counters[node.name]
                
                # Ожидаем перед следующей проверкой
                time.sleep(node.check_interval)
                
            except Exception as e:
                print(f"Ошибка при мониторинге {node.name}: {str(e)}")
                time.sleep(30)  # Ждем перед повторной попыткой
    
    def start(self) -> None:
        """Запускает мониторинг всех узлов"""
        self.is_running = True
        threads = []
        
        for node in self.nodes:
            thread = threading.Thread(
                target=self._monitor_node,
                args=(node,),
                daemon=True
            )
            thread.start()
            threads.append(thread)
        
        print("Мониторинг запущен. Нажмите Ctrl+C для остановки.")
        
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self) -> None:
        """Останавливает мониторинг"""
        self.is_running = False
        print("Мониторинг остановлен.")


# Пример использования
if __name__ == "__main__":
    # Пример конфигурации узлов
    nodes_to_monitor = [
        ServiceNode(
            name="Основная база данных",
            url="http://database.internal:5432/health",
            check_interval=30,
            timeout=3,
            expected_status=200
        ),
        ServiceNode(
            name="Платежный API",
            url="https://api.payments.com/health",
            check_interval=60,
            timeout=5,
            expected_status=200
        ),
        ServiceNode(
            name="Сервис аутентификации",
            url="https://auth.internal/api/health",
            check_interval=45,
            timeout=4,
            expected_status=200
        ),
    ]
    
    # Пример конфигурации уведомлений (Slack)
    slack_config = NotificationConfig(
        type=NotificationType.SLACK,
        webhook_url="https://hooks.slack.com/services/XXX/YYY/ZZZ",
        enabled=True
    )
    
    # Альтернативная конфигурация для email
    email_config = NotificationConfig(
        type=NotificationType.EMAIL,
        email_config={
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'username': 'monitor@company.com',
            'password': 'password',
            'from_email': 'monitor@company.com',
            'to_email': 'admin@company.com'
        },
        enabled=True
    )
    
    # Создаем и запускаем монитор
    monitor = ServiceMonitor(
        nodes=nodes_to_monitor,
        notification_config=slack_config,  # или email_config
        retry_count=2
    )
    
    # Запускаем мониторинг
    monitor.start()