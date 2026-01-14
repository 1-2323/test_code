from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, List, Tuple
from fastapi import FastAPI, Request, Response, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import secrets
import hashlib
import json
import re
import ipaddress

# Инициализация приложения
app = FastAPI(title="Session Monitoring Service", version="1.0.0")

# Конфигурация системы мониторинга сессий
SESSION_MONITORING_CONFIG = {
    'session_token_length': 32,
    'session_ttl_hours': 24,
    'device_fingerprint_ttl_days': 90,
    'max_sessions_per_user': 5,
    'suspicious_ip_threshold': 3,
    'suspicious_device_threshold': 2,
    'anomaly_check_window_hours': 1,
    'geoip_enabled': False,
    'require_device_fingerprint': True,
    'enable_ip_whitelist': False,
    'enable_ip_blacklist': True,
    'enable_rate_limiting': True
}

# Модели данных
class SessionData(BaseModel):
    session_id: str
    user_id: int
    username: str
    created_at: datetime
    expires_at: datetime
    last_accessed: datetime
    ip_address: str
    user_agent: str
    device_fingerprint: str
    location_data: Optional[Dict[str, Any]]
    is_suspicious: bool = False
    suspicious_reason: Optional[str] = None
    login_method: str = "password"  # password, 2fa, social, etc.

class DeviceFingerprint(BaseModel):
    fingerprint_hash: str
    user_id: int
    first_seen: datetime
    last_seen: datetime
    user_agent: str
    ip_address: str
    is_trusted: bool = False
    trust_level: int = 0  # 0-10, где 10 максимальное доверие

class SecurityEvent(BaseModel):
    event_id: str
    user_id: int
    event_type: str  # login, logout, session_create, session_destroy, suspicious_activity
    ip_address: str
    user_agent: str
    timestamp: datetime
    details: Dict[str, Any]
    severity: str  # info, warning, critical

# Хранилища данных (в реальном проекте заменить на БД/Redis)
sessions_storage: Dict[str, SessionData] = {}
device_fingerprints: Dict[str, DeviceFingerprint] = {}
security_events: List[SecurityEvent] = []
user_sessions_index: Dict[int, List[str]] = {}

# Белые и черные списки IP
ip_whitelist: List[str] = []
ip_blacklist: List[str] = []

# Хранилище пользователей
fake_users_db = {
    1: {
        "id": 1,
        "username": "user1",
        "email": "user1@example.com",
        "hashed_password": hashlib.sha256("password123!".encode()).hexdigest(),
        "is_active": True,
        "last_login": None,
        "failed_login_attempts": 0
    }
}

security = HTTPBearer()

# Утилиты для работы с IP
def is_ip_in_subnet(ip: str, subnet: str) -> bool:
    """Проверка, находится ли IP в подсети"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        network_obj = ipaddress.ip_network(subnet, strict=False)
        return ip_obj in network_obj
    except ValueError:
        return False

def is_ip_allowed(ip: str) -> Tuple[bool, Optional[str]]:
    """Проверка IP по белым и черным спискам"""
    # Проверка черного списка
    for blocked_ip in ip_blacklist:
        if is_ip_in_subnet(ip, blocked_ip):
            return False, f"IP заблокирован: {blocked_ip}"
    
    # Если включен белый список, проверяем его
    if SESSION_MONITORING_CONFIG['enable_ip_whitelist'] and ip_whitelist:
        allowed = False
        for allowed_ip in ip_whitelist:
            if is_ip_in_subnet(ip, allowed_ip):
                allowed = True
                break
        if not allowed:
            return False, "IP не в белом списке"
    
    return True, None

# Утилиты для создания отпечатка устройства
def generate_device_fingerprint(user_agent: str, ip: str, additional_data: Optional[Dict] = None) -> str:
    """Создание хеша отпечатка устройства"""
    fingerprint_data = {
        'user_agent': user_agent,
        'ip': ip,
        'screen_resolution': additional_data.get('screen_resolution') if additional_data else None,
        'timezone': additional_data.get('timezone') if additional_data else None,
        'language': additional_data.get('language') if additional_data else None,
        'platform': additional_data.get('platform') if additional_data else None
    }
    
    # Убираем None значения
    fingerprint_data = {k: v for k, v in fingerprint_data.items() if v is not None}
    
    # Создаем JSON строку и хешируем
    fingerprint_str = json.dumps(fingerprint_data, sort_keys=True)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()

def analyze_user_agent(user_agent: str) -> Dict[str, str]:
    """Анализ User-Agent строки"""
    result = {
        'browser': 'unknown',
        'os': 'unknown',
        'device': 'desktop',
        'is_mobile': False,
        'is_bot': False
    }
    
    # Простой парсинг User-Agent (в реальном проекте использовать специализированную библиотеку)
    user_agent_lower = user_agent.lower()
    
    # Определение бота
    bot_patterns = ['bot', 'crawler', 'spider', 'scraper', 'monitoring']
    if any(pattern in user_agent_lower for pattern in bot_patterns):
        result['is_bot'] = True
    
    # Определение мобильного устройства
    mobile_patterns = ['mobile', 'android', 'iphone', 'ipad', 'tablet']
    if any(pattern in user_agent_lower for pattern in mobile_patterns):
        result['is_mobile'] = True
        result['device'] = 'mobile'
    
    # Определение браузера
    if 'chrome' in user_agent_lower:
        result['browser'] = 'chrome'
    elif 'firefox' in user_agent_lower:
        result['browser'] = 'firefox'
    elif 'safari' in user_agent_lower:
        result['browser'] = 'safari'
    elif 'edge' in user_agent_lower:
        result['browser'] = 'edge'
    
    # Определение ОС
    if 'windows' in user_agent_lower:
        result['os'] = 'windows'
    elif 'linux' in user_agent_lower:
        result['os'] = 'linux'
    elif 'mac' in user_agent_lower:
        result['os'] = 'macos'
    elif 'android' in user_agent_lower:
        result['os'] = 'android'
    elif 'iphone' in user_agent_lower or 'ipad' in user_agent_lower:
        result['os'] = 'ios'
    
    return result

# Мониторинг и анализ сессий
class SessionMonitor:
    """Система мониторинга и проверки сессий"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    def check_session_health(self, session: SessionData) -> Tuple[bool, Optional[str]]:
        """Проверка здоровья сессии"""
        # Проверка срока действия
        if datetime.now() > session.expires_at:
            return False, "Сессия истекла"
        
        # Проверка частоты доступа (аномалии)
        time_since_last_access = datetime.now() - session.last_accessed
        
        # Если сессия была неактивна слишком долго (например, более 1 часа)
        if time_since_last_access.total_seconds() > 3600:
            # В реальном проекте можно потребовать повторную аутентификацию
            session.is_suspicious = True
            session.suspicious_reason = "Длительная неактивность"
            return True, "warning"
        
        return True, None
    
    def detect_suspicious_activity(self, session: SessionData, request: Request) -> Tuple[bool, Optional[str]]:
        """Обнаружение подозрительной активности"""
        suspicious_reasons = []
        
        # Проверка IP адреса
        ip_allowed, ip_reason = is_ip_allowed(session.ip_address)
        if not ip_allowed:
            suspicious_reasons.append(f"IP проблема: {ip_reason}")
        
        # Проверка на частую смену IP (если есть история сессий)
        user_sessions = user_sessions_index.get(session.user_id, [])
        unique_ips = set()
        
        for session_id in user_sessions:
            if session_id in sessions_storage:
                other_session = sessions_storage[session_id]
                # Учитываем только активные сессии за последний час
                time_diff = datetime.now() - other_session.created_at
                if time_diff.total_seconds() < 3600:
                    unique_ips.add(other_session.ip_address)
        
        if len(unique_ips) > self.config['suspicious_ip_threshold']:
            suspicious_reasons.append(f"Слишком много разных IP адресов: {len(unique_ips)}")
        
        # Проверка устройства
        if self.config['require_device_fingerprint']:
            device_hash = generate_device_fingerprint(
                session.user_agent,
                session.ip_address
            )
            
            # Проверяем, известно ли это устройство
            known_device = device_fingerprints.get(device_hash)
            if known_device:
                # Проверяем уровень доверия
                if known_device.trust_level < 5 and not known_device.is_trusted:
                    suspicious_reasons.append("Низкий уровень доверия устройства")
            else:
                # Новое устройство
                suspicious_reasons.append("Неизвестное устройство")
        
        # Проверка User-Agent на аномалии
        ua_analysis = analyze_user_agent(session.user_agent)
        if ua_analysis['is_bot']:
            suspicious_reasons.append("Обнаружен бот/сканер")
        
        # Проверка географической локации (если включена)
        if self.config['geoip_enabled'] and session.location_data:
            # В реальном проекте сравнивать с обычной локацией пользователя
            pass
        
        if suspicious_reasons:
            session.is_suspicious = True
            session.suspicious_reason = "; ".join(suspicious_reasons)
            return True, session.suspicious_reason
        
        return False, None
    
    def update_device_fingerprint(self, session: SessionData):
        """Обновление информации об устройстве"""
        device_hash = generate_device_fingerprint(
            session.user_agent,
            session.ip_address
        )
        
        now = datetime.now()
        
        if device_hash in device_fingerprints:
            device = device_fingerprints[device_hash]
            device.last_seen = now
            
            # Повышаем уровень доверия при успешных входах
            if not session.is_suspicious:
                device.trust_level = min(device.trust_level + 1, 10)
        else:
            device = DeviceFingerprint(
                fingerprint_hash=device_hash,
                user_id=session.user_id,
                first_seen=now,
                last_seen=now,
                user_agent=session.user_agent,
                ip_address=session.ip_address,
                is_trusted=False,
                trust_level=1
            )
            device_fingerprints[device_hash] = device
        
        # Удаляем старые отпечатки
        self.cleanup_old_device_fingerprints()
    
    def cleanup_old_device_fingerprints(self):
        """Очистка старых отпечатков устройств"""
        cutoff_date = datetime.now() - timedelta(days=self.config['device_fingerprint_ttl_days'])
        
        old_fingerprints = [
            fp_hash for fp_hash, device in device_fingerprints.items()
            if device.last_seen < cutoff_date
        ]
        
        for fp_hash in old_fingerprints:
            del device_fingerprints[fp_hash]
    
    def enforce_session_limits(self, user_id: int):
        """Ограничение количества одновременных сессий"""
        if user_id not in user_sessions_index:
            return
        
        user_sessions = user_sessions_index[user_id]
        
        if len(user_sessions) > self.config['max_sessions_per_user']:
            # Удаляем самые старые сессии
            sessions_to_remove = len(user_sessions) - self.config['max_sessions_per_user']
            
            # Сортируем сессии по времени создания
            sorted_sessions = sorted(
                user_sessions,
                key=lambda sid: sessions_storage[sid].created_at if sid in sessions_storage else datetime.min
            )
            
            for i in range(sessions_to_remove):
                session_id = sorted_sessions[i]
                if session_id in sessions_storage:
                    del sessions_storage[session_id]
                if session_id in user_sessions:
                    user_sessions.remove(session_id)
    
    def log_security_event(self, event_type: str, user_id: int, 
                          ip_address: str, user_agent: str, details: Dict[str, Any]):
        """Логирование событий безопасности"""
        event = SecurityEvent(
            event_id=secrets.token_hex(8),
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            timestamp=datetime.now(),
            details=details,
            severity=details.get('severity', 'info')
        )
        
        security_events.append(event)
        
        # В реальном проекте сохранять в БД и ограничивать размер лога
        if len(security_events) > 10000:
            security_events.pop(0)
    
    def analyze_session_patterns(self, user_id: int) -> Dict[str, Any]:
        """Анализ паттернов сессий пользователя"""
        if user_id not in user_sessions_index:
            return {"status": "no_sessions"}
        
        user_sessions = user_sessions_index[user_id]
        active_sessions = []
        
        for session_id in user_sessions:
            if session_id in sessions_storage:
                session = sessions_storage[session_id]
                if datetime.now() < session.expires_at:
                    active_sessions.append(session)
        
        if not active_sessions:
            return {"status": "no_active_sessions"}
        
        # Анализ IP адресов
        unique_ips = set(session.ip_address for session in active_sessions)
        
        # Анализ устройств
        unique_devices = set()
        for session in active_sessions:
            device_hash = generate_device_fingerprint(
                session.user_agent,
                session.ip_address
            )
            unique_devices.add(device_hash)
        
        # Анализ временных паттернов
        now = datetime.now()
        recent_sessions = [
            session for session in active_sessions
            if (now - session.created_at).total_seconds() < 3600  # Последний час
        ]
        
        return {
            "status": "analyzed",
            "total_active_sessions": len(active_sessions),
            "unique_ip_addresses": len(unique_ips),
            "unique_devices": len(unique_devices),
            "recent_sessions_last_hour": len(recent_sessions),
            "has_suspicious_sessions": any(session.is_suspicious for session in active_sessions)
        }

# Инициализация монитора сессий
session_monitor = SessionMonitor(SESSION_MONITORING_CONFIG)

# Middleware для проверки сессий
class SessionMonitoringMiddleware:
    """Middleware для мониторинга и проверки сессий при каждом запросе"""
    
    def __init__(self, app):
        self.app = app
        self.session_monitor = session_monitor
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        
        request = Request(scope, receive)
        response = await self.process_request(request)
        
        if response:
            await response(scope, receive, send)
        else:
            await self.app(scope, receive, send)
    
    async def process_request(self, request: Request) -> Optional[Response]:
        """Обработка входящего запроса с проверкой сессии"""
        
        # Исключаем публичные эндпоинты из проверки сессий
        public_paths = ['/login', '/register', '/health', '/docs', '/openapi.json']
        if any(request.url.path.startswith(path) for path in public_paths):
            return None
        
        # Получаем токен сессии из заголовка или cookie
        session_token = None
        
        # Из заголовка Authorization
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.replace("Bearer ", "")
        
        # Из cookie
        if not session_token:
            session_token = request.cookies.get("session_token")
        
        if not session_token:
            # Запрос без сессии
            self.session_monitor.log_security_event(
                event_type="unauthorized_access",
                user_id=0,
                ip_address=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("user-agent", "unknown"),
                details={
                    "path": request.url.path,
                    "method": request.method,
                    "severity": "warning"
                }
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Требуется аутентификация"}
            )
        
        # Получаем данные сессии
        session_data = sessions_storage.get(session_token)
        if not session_data:
            # Недействительная сессия
            self.session_monitor.log_security_event(
                event_type="invalid_session",
                user_id=0,
                ip_address=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("user-agent", "unknown"),
                details={
                    "session_token": session_token[:10] + "...",
                    "path": request.url.path,
                    "severity": "warning"
                }
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Недействительная сессия"}
            )
        
        # Проверяем здоровье сессии
        session_ok, session_message = self.session_monitor.check_session_health(session_data)
        if not session_ok:
            # Удаляем просроченную сессию
            self.destroy_session(session_token)
            
            self.session_monitor.log_security_event(
                event_type="session_expired",
                user_id=session_data.user_id,
                ip_address=session_data.ip_address,
                user_agent=session_data.user_agent,
                details={
                    "reason": session_message,
                    "severity": "info"
                }
            )
            
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": session_message}
            )
        
        # Обновляем информацию о текущем запросе
        current_ip = request.client.host if request.client else "unknown"
        current_user_agent = request.headers.get("user-agent", "unknown")
        
        # Проверяем, не изменились ли IP или устройство
        if (current_ip != session_data.ip_address or 
            current_user_agent != session_data.user_agent):
            
            # Обновляем информацию в сессии
            session_data.ip_address = current_ip
            session_data.user_agent = current_user_agent
            session_data.device_fingerprint = generate_device_fingerprint(
                current_user_agent,
                current_ip
            )
        
        # Обновляем время последнего доступа
        session_data.last_accessed = datetime.now()
        sessions_storage[session_token] = session_data
        
        # Проверяем на подозрительную активность
        is_suspicious, reason = self.session_monitor.detect_suspicious_activity(
            session_data, request
        )
        
        if is_suspicious:
            self.session_monitor.log_security_event(
                event_type="suspicious_activity",
                user_id=session_data.user_id,
                ip_address=session_data.ip_address,
                user_agent=session_data.user_agent,
                details={
                    "reason": reason,
                    "path": request.url.path,
                    "session_id": session_token[:10] + "...",
                    "severity": "critical"
                }
            )
            
            # Для критических нарушений можно закрыть сессию
            if "IP заблокирован" in reason or "Обнаружен бот" in reason:
                self.destroy_session(session_token)
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Доступ заблокирован по соображениям безопасности"}
                )
        
        # Обновляем информацию об устройстве
        self.session_monitor.update_device_fingerprint(session_data)
        
        # Добавляем информацию о сессии в request.state
        request.state.session = session_data
        request.state.session_token = session_token
        
        return None
    
    def destroy_session(self, session_token: str):
        """Уничтожение сессии"""
        if session_token in sessions_storage:
            session_data = sessions_storage[session_token]
            user_id = session_data.user_id
            
            # Удаляем из индекса пользователя
            if user_id in user_sessions_index:
                if session_token in user_sessions_index[user_id]:
                    user_sessions_index[user_id].remove(session_token)
            
            # Удаляем из хранилища
            del sessions_storage[session_token]

# Подключаем middleware
app.add_middleware(SessionMonitoringMiddleware)

# Зависимость для получения текущей сессии
def get_current_session(request: Request) -> SessionData:
    """Получение текущей сессии из request.state"""
    session = getattr(request.state, 'session', None)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия не найдена"
        )
    return session

# Эндпоинты для управления сессиями
@app.post("/session/create", status_code=status.HTTP_201_CREATED)
async def create_session_endpoint(
    user_id: int,
    username: str,
    login_method: str = "password",
    request: Request = None
):
    """Создание новой сессии (вызывается после успешной аутентификации)"""
    if not request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Отсутствует информация о запросе"
        )
    
    # Проверяем существование пользователя
    if user_id not in fake_users_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    # Генерируем токен сессии
    session_token = secrets.token_urlsafe(SESSION_MONITORING_CONFIG['session_token_length'])
    
    # Получаем информацию о клиенте
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Создаем отпечаток устройства
    device_fingerprint = generate_device_fingerprint(user_agent, ip_address)
    
    now = datetime.now()
    expires_at = now + timedelta(hours=SESSION_MONITORING_CONFIG['session_ttl_hours'])
    
    # Создаем объект сессии
    session_data = SessionData(
        session_id=session_token,
        user_id=user_id,
        username=username,
        created_at=now,
        expires_at=expires_at,
        last_accessed=now,
        ip_address=ip_address,
        user_agent=user_agent,
        device_fingerprint=device_fingerprint,
        location_data=None,
        login_method=login_method
    )
    
    # Сохраняем сессию
    sessions_storage[session_token] = session_data
    
    # Обновляем индекс пользователя
    if user_id not in user_sessions_index:
        user_sessions_index[user_id] = []
    user_sessions_index[user_id].append(session_token)
    
    # Применяем лимиты сессий
    session_monitor.enforce_session_limits(user_id)
    
    # Логируем событие
    session_monitor.log_security_event(
        event_type="session_create",
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "login_method": login_method,
            "session_id": session_token[:10] + "...",
            "severity": "info"
        }
    )
    
    return {
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "device_fingerprint": device_fingerprint[:16] + "..."
    }

@app.get("/session/status")
async def get_session_status(session: SessionData = Depends(get_current_session)):
    """Получение статуса текущей сессии"""
    return {
        "user_id": session.user_id,
        "username": session.username,
        "created_at": session.created_at.isoformat(),
        "last_accessed": session.last_accessed.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "ip_address": session.ip_address,
        "is_suspicious": session.is_suspicious,
        "suspicious_reason": session.suspicious_reason,
        "device_fingerprint": session.device_fingerprint[:16] + "...",
        "login_method": session.login_method
    }

@app.get("/sessions/active")
async def get_active_sessions(user_id: int, session: SessionData = Depends(get_current_session)):
    """Получение активных сессий пользователя (только для своего аккаунта)"""
    if session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к сессиям другого пользователя"
        )
    
    active_sessions = []
    if user_id in user_sessions_index:
        for session_id in user_sessions_index[user_id]:
            if session_id in sessions_storage:
                s = sessions_storage[session_id]
                if datetime.now() < s.expires_at:
                    active_sessions.append({
                        "session_id": s.session_id[:16] + "...",
                        "created_at": s.created_at.isoformat(),
                        "last_accessed": s.last_accessed.isoformat(),
                        "ip_address": s.ip_address,
                        "user_agent": analyze_user_agent(s.user_agent),
                        "is_suspicious": s.is_suspicious,
                        "device_fingerprint": s.device_fingerprint[:16] + "..."
                    })
    
    return {
        "total_active_sessions": len(active_sessions),
        "sessions": active_sessions
    }

@app.post("/session/terminate/{session_id}")
async def terminate_session(session_id: str, session: SessionData = Depends(get_current_session)):
    """Завершение конкретной сессии"""
    if session_id not in sessions_storage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сессия не найдена"
        )
    
    target_session = sessions_storage[session_id]
    
    # Проверяем права доступа
    if session.user_id != target_session.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет прав для завершения этой сессии"
        )
    
    # Удаляем сессию
    if session_id in user_sessions_index.get(target_session.user_id, []):
        user_sessions_index[target_session.user_id].remove(session_id)
    
    del sessions_storage[session_id]
    
    session_monitor.log_security_event(
        event_type="session_terminate",
        user_id=session.user_id,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
        details={
            "terminated_session": session_id[:10] + "...",
            "terminated_by": session.session_id[:10] + "...",
            "severity": "info"
        }
    )
    
    return {"status": "success", "message": "Сессия завершена"}

@app.post("/session/terminate-all-others")
async def terminate_all_other_sessions(session: SessionData = Depends(get_current_session)):
    """Завершение всех других сессий пользователя"""
    user_id = session.user_id
    
    if user_id not in user_sessions_index:
        return {"status": "success", "terminated_count": 0}
    
    terminated_count = 0
    sessions_to_terminate = []
    
    for session_id in user_sessions_index[user_id]:
        if session_id != session.session_id and session_id in sessions_storage:
            sessions_to_terminate.append(session_id)
    
    for session_id in sessions_to_terminate:
        del sessions_storage[session_id]
        user_sessions_index[user_id].remove(session_id)
        terminated_count += 1
    
    session_monitor.log_security_event(
        event_type="session_terminate_all",
        user_id=user_id,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
        details={
            "terminated_count": terminated_count,
            "kept_session": session.session_id[:10] + "...",
            "severity": "info"
        }
    )
    
    return {"status": "success", "terminated_count": terminated_count}

@app.get("/security/events")
async def get_security_events(
    limit: int = 100,
    severity: Optional[str] = None,
    session: SessionData = Depends(get_current_session)
):
    """Получение событий безопасности (только для администраторов)"""
    # В реальном проекте проверять права администратора
    filtered_events = security_events
    
    if severity:
        filtered_events = [e for e in filtered_events if e.severity == severity]
    
    # Ограничиваем количество
    filtered_events = filtered_events[-limit:]
    
    return {
        "total_events": len(security_events),
        "filtered_events": len(filtered_events),
        "events": [
            {
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat(),
                "user_id": e.user_id,
                "ip_address": e.ip_address,
                "severity": e.severity,
                "details": e.details
            }
            for e in reversed(filtered_events)
        ]
    }

@app.get("/monitoring/session-patterns")
async def get_session_patterns(session: SessionData = Depends(get_current_session)):
    """Анализ паттернов сессий текущего пользователя"""
    patterns = session_monitor.analyze_session_patterns(session.user_id)
    return patterns

# Эндпоинт для проверки работы системы
@app.get("/health")
async def health_check():
    """Проверка работоспособности системы"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "sessions_count": len(sessions_storage),
        "devices_count": len(device_fingerprints),
        "events_count": len(security_events)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)