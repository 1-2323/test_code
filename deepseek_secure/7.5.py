import hashlib
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, Set
from dataclasses import dataclass, asdict, field
from uuid import uuid4
from ipaddress import ip_address
import re

# =================== КОНФИГУРАЦИЯ ===================
SESSION_TIMEOUT = 1800  # 30 минут
MAX_SESSIONS_PER_USER = 5
SUSPICIOUS_IP_CHANGE = True
SUSPICIOUS_DEVICE_CHANGE = True
ALLOW_MULTIPLE_IPS = False  # Разрешить несколько IP для одной сессии

# =================== МОДЕЛИ ДАННЫХ ===================

@dataclass
class DeviceInfo:
    """Информация об устройстве пользователя"""
    user_agent: str
    platform: str
    browser: str
    device_type: str  # mobile, desktop, tablet
    screen_resolution: str = ""
    language: str = ""
    timezone: str = ""
    
    def fingerprint(self) -> str:
        """Создает цифровой отпечаток устройства"""
        data = f"{self.user_agent}|{self.platform}|{self.browser}|{self.device_type}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

@dataclass
class SessionData:
    """Данные сессии"""
    session_id: str
    user_id: str
    ip_address: str
    device: DeviceInfo
    created_at: float
    last_activity: float
    is_active: bool = True
    login_location: Optional[str] = None
    session_token: str = field(default_factory=lambda: str(uuid4()))
    
    def to_dict(self) -> Dict:
        """Конвертация в словарь для сериализации"""
        data = asdict(self)
        data['device'] = asdict(self.device)
        return data

@dataclass
class SecurityAlert:
    """Предупреждение о безопасности"""
    alert_id: str
    user_id: str
    alert_type: str
    severity: str  # low, medium, high
    message: str
    timestamp: float
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

# =================== СИСТЕМА МОНИТОРИНГА ===================

class SessionMonitor:
    """Система мониторинга сессий"""
    
    def __init__(self, storage_backend=None):
        self.sessions: Dict[str, SessionData] = {}
        self.user_sessions: Dict[str, Set[str]] = {}
        self.security_alerts: Dict[str, SecurityAlert] = {}
        self.ip_whitelist: Set[str] = set()
        self.suspicious_patterns = {
            'ip_changes': 0,
            'device_changes': 0,
            'multiple_countries': 0
        }
        
    def create_session(self, user_id: str, ip: str, device_info: Dict) -> Tuple[SessionData, Optional[SecurityAlert]]:
        """Создание новой сессии"""
        # Валидация IP
        if not self._validate_ip(ip):
            raise ValueError(f"Invalid IP address: {ip}")
        
        # Ограничение количества сессий
        self._cleanup_old_sessions(user_id)
        
        device = DeviceInfo(**device_info)
        session_id = str(uuid4())
        
        session = SessionData(
            session_id=session_id,
            user_id=user_id,
            ip_address=ip,
            device=device,
            created_at=time.time(),
            last_activity=time.time()
        )
        
        # Сохраняем сессию
        self.sessions[session_id] = session
        
        # Добавляем в индекс пользователя
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = set()
        self.user_sessions[user_id].add(session_id)
        
        # Проверка на подозрительную активность
        alert = self._check_suspicious_activity(user_id, session)
        
        return session, alert
    
    def validate_session(self, session_id: str, current_ip: str, 
                         current_device: Dict) -> Tuple[bool, Optional[SecurityAlert], Optional[SessionData]]:
        """Валидация сессии при каждом запросе"""
        if session_id not in self.sessions:
            return False, None, None
        
        session = self.sessions[session_id]
        
        # Проверка таймаута
        if time.time() - session.last_activity > SESSION_TIMEOUT:
            session.is_active = False
            return False, None, None
        
        # Проверка активности
        if not session.is_active:
            return False, None, None
        
        # Обновляем время последней активности
        session.last_activity = time.time()
        
        # Проверяем безопасность
        alert = self._perform_security_checks(session, current_ip, current_device)
        
        return True, alert, session
    
    def _perform_security_checks(self, session: SessionData, 
                                current_ip: str, current_device: Dict) -> Optional[SecurityAlert]:
        """Выполнение проверок безопасности"""
        current_device_obj = DeviceInfo(**current_device)
        alerts = []
        
        # 1. Проверка IP адреса
        if SUSPICIOUS_IP_CHANGE and session.ip_address != current_ip:
            if not ALLOW_MULTIPLE_IPS:
                alert = self._create_ip_change_alert(session, current_ip)
                alerts.append(alert)
                session.is_active = False  # Блокируем сессию
        
        # 2. Проверка устройства
        if SUSPICIOUS_DEVICE_CHANGE:
            if session.device.fingerprint() != current_device_obj.fingerprint():
                alert = self._create_device_change_alert(session, current_device_obj)
                alerts.append(alert)
                session.is_active = False  # Блокируем сессию
        
        # 3. Проверка геолокации (упрощенная)
        geo_alert = self._check_geolocation(session, current_ip)
        if geo_alert:
            alerts.append(geo_alert)
        
        # 4. Проверка частоты запросов
        freq_alert = self._check_request_frequency(session)
        if freq_alert:
            alerts.append(freq_alert)
        
        return alerts[0] if alerts else None
    
    def _create_ip_change_alert(self, session: SessionData, new_ip: str) -> SecurityAlert:
        """Создание предупреждения об изменении IP"""
        return SecurityAlert(
            alert_id=str(uuid4()),
            user_id=session.user_id,
            alert_type="IP_CHANGE",
            severity="high",
            message=f"IP address changed from {session.ip_address} to {new_ip}",
            timestamp=time.time(),
            session_id=session.session_id,
            ip_address=new_ip,
            metadata={
                "old_ip": session.ip_address,
                "new_ip": new_ip,
                "session_age": time.time() - session.created_at
            }
        )
    
    def _create_device_change_alert(self, session: SessionData, 
                                   new_device: DeviceInfo) -> SecurityAlert:
        """Создание предупреждения об изменении устройства"""
        return SecurityAlert(
            alert_id=str(uuid4()),
            user_id=session.user_id,
            alert_type="DEVICE_CHANGE",
            severity="high",
            message=f"Device changed from {session.device.device_type} to {new_device.device_type}",
            timestamp=time.time(),
            session_id=session.session_id,
            ip_address=session.ip_address,
            metadata={
                "old_device": asdict(session.device),
                "new_device": asdict(new_device)
            }
        )
    
    def _check_geolocation(self, session: SessionData, current_ip: str) -> Optional[SecurityAlert]:
        """Проверка геолокации (заглушка для демонстрации)"""
        # Здесь можно интегрировать с GeoIP базой
        # Для примера просто проверяем, что IP из одного диапазона
        try:
            old_ip_num = int(ip_address(session.ip_address))
            new_ip_num = int(ip_address(current_ip))
            
            # Если IP из разных подсетей (первые 2 октета разные)
            if (old_ip_num >> 16) != (new_ip_num >> 16):
                return SecurityAlert(
                    alert_id=str(uuid4()),
                    user_id=session.user_id,
                    alert_type="GEO_LOCATION_CHANGE",
                    severity="medium",
                    message=f"Possible location change detected",
                    timestamp=time.time(),
                    session_id=session.session_id,
                    metadata={
                        "old_ip": session.ip_address,
                        "new_ip": current_ip
                    }
                )
        except:
            pass
        
        return None
    
    def _check_request_frequency(self, session: SessionData) -> Optional[SecurityAlert]:
        """Проверка частоты запросов"""
        # Здесь можно добавить логику анализа частоты запросов
        # Для демонстрации всегда возвращаем None
        return None
    
    def _check_suspicious_activity(self, user_id: str, session: SessionData) -> Optional[SecurityAlert]:
        """Проверка подозрительной активности при создании сессии"""
        user_sessions = self.get_user_sessions(user_id)
        
        # Проверка множественных сессий
        if len(user_sessions) > MAX_SESSIONS_PER_USER:
            return SecurityAlert(
                alert_id=str(uuid4()),
                user_id=user_id,
                alert_type="MULTIPLE_SESSIONS",
                severity="medium",
                message=f"User has {len(user_sessions)} active sessions",
                timestamp=time.time(),
                session_id=session.session_id
            )
        
        return None
    
    def _cleanup_old_sessions(self, user_id: str):
        """Очистка старых сессий пользователя"""
        if user_id not in self.user_sessions:
            return
        
        current_time = time.time()
        sessions_to_remove = []
        
        for session_id in self.user_sessions[user_id]:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                if not session.is_active or (current_time - session.last_activity > SESSION_TIMEOUT):
                    sessions_to_remove.append(session_id)
        
        for session_id in sessions_to_remove:
            self.user_sessions[user_id].remove(session_id)
            if session_id in self.sessions:
                del self.sessions[session_id]
        
        # Если у пользователя слишком много сессий, удаляем самые старые
        while len(self.user_sessions[user_id]) > MAX_SESSIONS_PER_USER:
            oldest_session_id = min(
                self.user_sessions[user_id],
                key=lambda sid: self.sessions[sid].created_at
            )
            self.user_sessions[user_id].remove(oldest_session_id)
            if oldest_session_id in self.sessions:
                del self.sessions[oldest_session_id]
    
    def get_user_sessions(self, user_id: str) -> Dict[str, SessionData]:
        """Получение всех активных сессий пользователя"""
        sessions = {}
        if user_id in self.user_sessions:
            for session_id in self.user_sessions[user_id]:
                if session_id in self.sessions and self.sessions[session_id].is_active:
                    sessions[session_id] = self.sessions[session_id]
        return sessions
    
    def terminate_session(self, session_id: str):
        """Завершение сессии"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.is_active = False
            
            # Удаляем из индекса пользователя
            if session.user_id in self.user_sessions:
                self.user_sessions[session.user_id].discard(session_id)
    
    def terminate_all_user_sessions(self, user_id: str, exclude_session_id: Optional[str] = None):
        """Завершение всех сессий пользователя"""
        if user_id in self.user_sessions:
            for session_id in list(self.user_sessions[user_id]):
                if session_id != exclude_session_id:
                    self.terminate_session(session_id)
    
    def _validate_ip(self, ip: str) -> bool:
        """Валидация IP адреса"""
        try:
            ip_address(ip)
            return True
        except:
            return False
    
    def add_to_whitelist(self, ip: str):
        """Добавление IP в белый список"""
        if self._validate_ip(ip):
            self.ip_whitelist.add(ip)
    
    def get_session_stats(self) -> Dict:
        """Получение статистики по сессиям"""
        active_sessions = sum(1 for s in self.sessions.values() if s.is_active)
        total_users = len(self.user_sessions)
        
        return {
            "total_sessions": len(self.sessions),
            "active_sessions": active_sessions,
            "total_users": total_users,
            "sessions_per_user": {
                user_id: len(sessions) 
                for user_id, sessions in self.user_sessions.items()
            }
        }
    
    def save_to_file(self, filename: str = "sessions_backup.json"):
        """Сохранение сессий в файл (для демонстрации)"""
        data = {
            "sessions": {sid: session.to_dict() for sid, session in self.sessions.items()},
            "user_sessions": {uid: list(sessions) for uid, sessions in self.user_sessions.items()},
            "timestamp": time.time()
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    def load_from_file(self, filename: str = "sessions_backup.json"):
        """Загрузка сессий из файла (для демонстрации)"""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            # Восстанавливаем сессии
            self.sessions.clear()
            for sid, session_data in data["sessions"].items():
                device_data = session_data.pop("device")
                device = DeviceInfo(**device_data)
                session = SessionData(**session_data, device=device)
                self.sessions[sid] = session
            
            # Восстанавливаем индексы
            self.user_sessions.clear()
            for uid, session_ids in data["user_sessions"].items():
                self.user_sessions[uid] = set(session_ids)
                
        except FileNotFoundError:
            pass

# =================== ИНТЕГРАЦИЯ С ВЕБ-ФРЕЙМВОРКОМ ===================

class SessionMiddleware:
    """Middleware для интеграции с веб-фреймворками"""
    
    def __init__(self, monitor: SessionMonitor):
        self.monitor = monitor
    
    def process_request(self, request):
        """Обработка входящего запроса"""
        # Этот метод нужно адаптировать под конкретный фреймворк
        # Пример для абстрактного request объекта:
        
        session_id = request.cookies.get('session_id')
        user_id = request.headers.get('X-User-ID')
        ip_address = request.remote_addr
        
        device_info = {
            'user_agent': request.headers.get('User-Agent', ''),
            'platform': self._detect_platform(request),
            'browser': self._detect_browser(request),
            'device_type': self._detect_device_type(request)
        }
        
        if session_id and user_id:
            is_valid, alert, session = self.monitor.validate_session(
                session_id, ip_address, device_info
            )
            
            if not is_valid:
                # Сессия невалидна
                request.session_valid = False
                if alert:
                    # Логируем предупреждение
                    self._log_alert(alert)
            else:
                request.session_valid = True
                request.session_data = session
                
                if alert:
                    # Логируем предупреждение, но разрешаем доступ
                    self._log_alert(alert)
        else:
            request.session_valid = False
    
    def _detect_platform(self, request) -> str:
        """Определение платформы"""
        user_agent = request.headers.get('User-Agent', '').lower()
        if 'windows' in user_agent:
            return 'Windows'
        elif 'linux' in user_agent:
            return 'Linux'
        elif 'mac' in user_agent:
            return 'MacOS'
        elif 'android' in user_agent:
            return 'Android'
        elif 'ios' in user_agent:
            return 'iOS'
        return 'Unknown'
    
    def _detect_browser(self, request) -> str:
        """Определение браузера"""
        user_agent = request.headers.get('User-Agent', '').lower()
        if 'chrome' in user_agent:
            return 'Chrome'
        elif 'firefox' in user_agent:
            return 'Firefox'
        elif 'safari' in user_agent:
            return 'Safari'
        elif 'edge' in user_agent:
            return 'Edge'
        return 'Unknown'
    
    def _detect_device_type(self, request) -> str:
        """Определение типа устройства"""
        user_agent = request.headers.get('User-Agent', '').lower()
        if 'mobile' in user_agent:
            return 'mobile'
        elif 'tablet' in user_agent:
            return 'tablet'
        return 'desktop'
    
    def _log_alert(self, alert: SecurityAlert):
        """Логирование предупреждений"""
        # Здесь можно добавить запись в лог, отправку уведомлений и т.д.
        print(f"[SECURITY ALERT] {alert.alert_type}: