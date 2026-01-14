import time
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import threading
from typing import Dict, List, Optional, Callable
import psycopg2
import requests
from requests.exceptions import RequestException
import json

class HealthMonitor:
    def __init__(self, config_path: str = 'config.json'):
        """Инициализация монитора здоровья"""
        self.config = self._load_config(config_path)
        self.setup_logging()
        self.alert_methods = []
        self._setup_alert_methods()
        self.last_alert_time: Dict[str, datetime] = {}
        self.alert_cooldown = self.config.get('alert_cooldown_seconds', 300)
        
    def _load_config(self, config_path: str) -> Dict:
        """Загрузка конфигурации из JSON файла"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logging.error(f"Конфигурационный файл {config_path} не найден")
            raise
        except json.JSONDecodeError:
            logging.error(f"Ошибка парсинга конфигурационного файла {config_path}")
            raise
    
    def setup_logging(self):
        """Настройка системы логирования"""
        log_level = getattr(logging, self.config.get('log_level', 'INFO'))
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config.get('log_file', 'health_monitor.log')),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _setup_alert_methods(self):
        """Настройка методов алертинга"""
        alert_config = self.config.get('alerting', {})
        
        # Email алертинг
        if alert_config.get('email', {}).get('enabled', False):
            self.alert_methods.append(self._send_email_alert)
        
        # Webhook алертинг
        if alert_config.get('webhook', {}).get('enabled', False):
            self.alert_methods.append(self._send_webhook_alert)
        
        # Slack алертинг
        if alert_config.get('slack', {}).get('enabled', False):
            self.alert_methods.append(self._send_slack_alert)
    
    def check_database(self) -> Dict:
        """Проверка соединения с базой данных"""
        db_config = self.config.get('database', {})
        result = {
            'service': 'database',
            'status': 'unknown',
            'response_time': None,
            'error': None,
            'timestamp': datetime.now().isoformat()
        }
        
        if not db_config:
            result['error'] = 'Database configuration not found'
            return result
        
        try:
            start_time = time.time()
            conn = psycopg2.connect(
                host=db_config.get('host'),
                port=db_config.get('port', 5432),
                database=db_config.get('database'),
                user=db_config.get('username'),
                password=db_config.get('password'),
                connect_timeout=5
            )
            
            # Выполняем простой запрос
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            
            conn.close()
            
            result['response_time'] = round((time.time() - start_time) * 1000, 2)
            result['status'] = 'healthy'
            
        except Exception as e:
            result['status'] = 'unhealthy'
            result['error'] = str(e)
            self.logger.error(f"Database check failed: {e}")
        
        return result
    
    def check_external_service(self, service_name: str, service_config: Dict) -> Dict:
        """Проверка внешнего сервиса"""
        result = {
            'service': service_name,
            'status': 'unknown',
            'response_time': None,
            'error': None,
            'timestamp': datetime.now().isoformat()
        }
        
        if not service_config.get('url'):
            result['error'] = 'Service URL not configured'
            return result
        
        try:
            start_time = time.time()
            response = requests.get(
                service_config['url'],
                timeout=service_config.get('timeout', 10),
                headers=service_config.get('headers', {}),
                verify=service_config.get('verify_ssl', True)
            )
            
            result['response_time'] = round((time.time() - start_time) * 1000, 2)
            
            # Проверяем HTTP статус код
            expected_status = service_config.get('expected_status', 200)
            if response.status_code == expected_status:
                
                # Дополнительная проверка содержимого ответа (опционально)
                if 'expected_content' in service_config:
                    if service_config['expected_content'] not in response.text:
                        result['status'] = 'unhealthy'
                        result['error'] = 'Expected content not found in response'
                    else:
                        result['status'] = 'healthy'
                else:
                    result['status'] = 'healthy'
            else:
                result['status'] = 'unhealthy'
                result['error'] = f"Unexpected status code: {response.status_code}"
                
        except RequestException as e:
            result['status'] = 'unhealthy'
            result['error'] = str(e)
            self.logger.error(f"Service {service_name} check failed: {e}")
        
        return result
    
    def _send_email_alert(self, alert_data: Dict):
        """Отправка алерта по email"""
        email_config = self.config['alerting']['email']
        
        try:
            msg = MIMEMultipart()
            msg['From'] = email_config['from_email']
            msg['To'] = ', '.join(email_config['to_emails'])
            msg['Subject'] = f"[Health Monitor Alert] {alert_data['service']} is {alert_data['status']}"
            
            body = f"""
            Service Health Alert
            
            Service: {alert_data['service']}
            Status: {alert_data['status']}
            Time: {alert_data['timestamp']}
            
            Details:
            {json.dumps(alert_data, indent=2, ensure_ascii=False)}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port']) as server:
                if email_config.get('use_tls', True):
                    server.starttls()
                if email_config.get('username') and email_config.get('password'):
                    server.login(email_config['username'], email_config['password'])
                server.send_message(msg)
            
            self.logger.info(f"Email alert sent for {alert_data['service']}")
            
        except Exception as e:
            self.logger.error(f"Failed to send email alert: {e}")
    
    def _send_webhook_alert(self, alert_data: Dict):
        """Отправка алерта через webhook"""
        webhook_config = self.config['alerting']['webhook']
        
        try:
            headers = webhook_config.get('headers', {'Content-Type': 'application/json'})
            response = requests.post(
                webhook_config['url'],
                json=alert_data,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            self.logger.info(f"Webhook alert sent for {alert_data['service']}")
            
        except Exception as e:
            self.logger.error(f"Failed to send webhook alert: {e}")
    
    def _send_slack_alert(self, alert_data: Dict):
        """Отправка алерта в Slack"""
        slack_config = self.config['alerting']['slack']
        
        try:
            message = {
                "text": f"🚨 Health Monitor Alert",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Service:* {alert_data['service']}\n*Status:* {alert_data['status']}\n*Time:* {alert_data['timestamp']}"
                        }
                    }
                ]
            }
            
            if alert_data.get('error'):
                message['blocks'].append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Error:* ```{alert_data['error']}```"
                    }
                })
            
            response = requests.post(
                slack_config['webhook_url'],
                json=message,
                timeout=10
            )
            response.raise_for_status()
            self.logger.info(f"Slack alert sent for {alert_data['service']}")
            
        except Exception as e:
            self.logger.error(f"Failed to send Slack alert: {e}")
    
    def should_send_alert(self, service_name: str) -> bool:
        """Проверка необходимости отправки алерта (регулировка частоты)"""
        if service_name not in self.last_alert_time:
            return True
        
        time_since_last_alert = (datetime.now() - self.last_alert_time[service_name]).total_seconds()
        return time_since_last_alert >= self.alert_cooldown
    
    def send_alerts(self, check_result: Dict):
        """Отправка алертов при обнаружении проблем"""
        if check_result['status'] != 'unhealthy':
            return
        
        if not self.should_send_alert(check_result['service']):
            self.logger.debug(f"Alert cooldown active for {check_result['service']}")
            return
        
        self.last_alert_time[check_result['service']] = datetime.now()
        
        for alert_method in self.alert_methods:
            try:
                alert_method(check_result)
            except Exception as e:
                self.logger.error(f"Alert method failed: {e}")
    
    def run_check(self) -> List[Dict]:
        """Выполнение всех проверок"""
        check_results = []
        
        # Проверка базы данных
        db_result = self.check_database()
        check_results.append(db_result)
        self.send_alerts(db_result)
        
        # Проверка внешних сервисов
        external_services = self.config.get('external_services', {})
        for service_name, service_config in external_services.items():
            if service_config.get('enabled', True):
                service_result = self.check_external_service(service_name, service_config)
                check_results.append(service_result)
                self.send_alerts(service_result)
        
        # Логирование результатов
        self.logger.info(f"Health check completed. Results: {check_results}")
        
        return check_results
    
    def start_monitoring(self):
        """Запуск периодического мониторинга"""
        interval = self.config.get('check_interval_seconds', 60)
        
        self.logger.info(f"Starting health monitoring with {interval} second interval")
        
        while True:
            try:
                self.run_check()
                time.sleep(interval)
            except KeyboardInterrupt:
                self.logger.info("Health monitoring stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in monitoring loop: {e}")
                time.sleep(interval)

def main():
    """Точка входа в приложение"""
    monitor = HealthMonitor('config.json')
    monitor.start_monitoring()

if __name__ == "__main__":
    main()