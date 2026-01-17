import hashlib
import logging
from typing import Dict, Any, Optional, Final
from fastapi import FastAPI, Request, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis

# --- Конфигурация безопасности ---
SESSION_PREFIX: Final[str] = "session:"
# Уровень строгости проверки IP (True - блокировать при смене, False - только логировать)
STRICT_IP_POLICY: Final[bool] = False

app = FastAPI()
redis_client = Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Настройка журнала безопасности
logging.basicConfig(level=logging.INFO)
security_logger = logging.getLogger("SecurityMonitor")

class SessionData(BaseModel):
    user_id: str
    ip_address: str
    fingerprint_hash: str

class SessionMonitor:
    """
    Система мониторинга сессий с проверкой контекста (IP и Fingerprint).
    Защищает от Session Hijacking.
    """

    def __init__(self, redis: Redis):
        self.redis = redis

    def _normalize_and_hash_fingerprint(self, raw_fingerprint: Dict[str, Any]) -> str:
        """
        Нормализует данные браузера и создает устойчивый криптографический хеш.
        """
        # Сортируем ключи для консистентности хеша
        normalized_str = "|".join(
            f"{k}:{str(v).strip().lower()}" 
            for k, v in sorted(raw_fingerprint.items())
        )
        return hashlib.sha256(normalized_str.encode()).hexdigest()

    async def validate_session_context(self, session_id: str, current_ip: str, raw_fp: Dict[str, Any]):
        """
        Сверяет текущий контекст запроса с данными, сохраненными в сессии.
        """
        session_key = f"{SESSION_PREFIX}{session_id}"
        stored_data_raw = await self.redis.hgetall(session_key)

        if not stored_data_raw:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

        current_fp_hash = self._normalize_and_hash_fingerprint(raw_fp)
        
        # 1. Проверка Fingerprint (строгая)
        if current_fp_hash != stored_data_raw.get("fingerprint_hash"):
            security_logger.warning(
                f"CRITICAL: Fingerprint mismatch for user {stored_data_raw.get('user_id')}. "
                f"Possible Session Hijacking! Session terminated."
            )
            await self.terminate_session(session_id)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Security context changed")

        # 2. Проверка IP-адреса (контролируемая)
        if current_ip != stored_data_raw.get("ip_address"):
            security_logger.info(
                f"NOTICE: IP address changed for user {stored_data_raw.get('user_id')} "
                f"from {stored_data_raw.get('ip_address')} to {current_ip}."
            )
            
            if STRICT_IP_POLICY:
                await self.terminate_session(session_id)
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP address mismatch")
            
            # Обновляем IP в сессии (допускаем мобильные сети/VPN), если политика не строгая
            await self.redis.hset(session_key, "ip_address", current_ip)

    async def terminate_session(self, session_id: str):
        """Принудительное завершение сессии."""
        await self.redis.delete(f"{SESSION_PREFIX}{session_id}")

# --- Пример интеграции в Middleware или Depends ---

async def get_current_user(request: Request):
    """
    Пример функции-зависимости для проверки каждой сессии.
    """
    monitor = SessionMonitor(redis_client)
    session_id = request.cookies.get("session_id")
    
    if not session_id:
        raise HTTPException(status_code=401)

    # В реальности Fingerprint собирается на фронтенде и передается в заголовке
    raw_fingerprint = {
        "user_agent": request.headers.get("user-agent"),
        "accept_language": request.headers.get("accept-language"),
        "screen_res": request.headers.get("x-screen-res") # Пример кастомного заголовка
    }
    
    await monitor.validate_session_context(
        session_id=session_id,
        current_ip=request.client.host,
        raw_fp=raw_fingerprint
    )
    return True