import hashlib
import ipaddress
import logging
from typing import Optional

import redis
from fastapi import FastAPI, Request, HTTPException, status, Depends

# =========================
# CONFIGURATION
# =========================

REDIS_URL = "redis://localhost:6379/0"
SESSION_TTL_SECONDS = 60 * 60
FINGERPRINT_MAX_LENGTH = 512

SESSION_PREFIX = "session"
SECURITY_LOG_FILE = "session_security.log"

# =========================
# LOGGING
# =========================

logger = logging.getLogger("session-security")
logger.setLevel(logging.INFO)
handler = logging.FileHandler(SECURITY_LOG_FILE)
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# =========================
# REDIS CLIENT
# =========================

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)

# =========================
# UTILITIES
# =========================

def normalize_fingerprint(fp: str) -> str:
    cleaned = "".join(ch for ch in fp if ch.isalnum() or ch in "-_:.")
    return cleaned[:FINGERPRINT_MAX_LENGTH]


def hash_fingerprint(fp: str) -> str:
    normalized = normalize_fingerprint(fp)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def ip_allowed(current_ip: str, original_ip: str) -> bool:
    """
    Допускаем изменение IP в пределах одной подсети /24 (IPv4).
    """
    try:
        net1 = ipaddress.ip_network(f"{original_ip}/24", strict=False)
        return ipaddress.ip_address(current_ip) in net1
    except Exception:
        return False


def session_key(session_id: str) -> str:
    return f"{SESSION_PREFIX}:{session_id}"


# =========================
# SESSION STORAGE FORMAT
# =========================
# {
#   "user_id": int,
#   "ip": str,
#   "fingerprint_hash": str
# }

# =========================
# SESSION MANAGER
# =========================

class SessionMonitor:
    def register_session(
        self,
        *,
        session_id: str,
        user_id: int,
        ip: str,
        fingerprint: str,
    ) -> None:
        redis_client.hset(
            session_key(session_id),
            mapping={
                "user_id": user_id,
                "ip": ip,
                "fingerprint_hash": hash_fingerprint(fingerprint),
            },
        )
        redis_client.expire(session_key(session_id), SESSION_TTL_SECONDS)

    def validate_session(
        self,
        *,
        session_id: str,
        current_ip: str,
        fingerprint: str,
    ) -> int:
        data = redis_client.hgetall(session_key(session_id))
        if not data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Сессия недействительна",
            )

        stored_ip = data["ip"]
        stored_fp_hash = data["fingerprint_hash"]
        current_fp_hash = hash_fingerprint(fingerprint)

        if not hmac_compare(stored_fp_hash, current_fp_hash):
            self._log_violation(session_id, "Fingerprint mismatch")
            self.invalidate_session(session_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Сессия завершена по соображениям безопасности",
            )

        if not ip_allowed(current_ip, stored_ip):
            self._log_violation(
                session_id,
                f"IP change detected: {stored_ip} -> {current_ip}",
            )

        return int(data["user_id"])

    def invalidate_session(self, session_id: str) -> None:
        redis_client.delete(session_key(session_id))

    def _log_violation(self, session_id: str, reason: str) -> None:
        logger.warning(
            "Session %s security deviation: %s",
            session_id,
            reason,
        )


def hmac_compare(a: str, b: str) -> bool:
    return hashlib.sha256(a.encode()).digest() == hashlib.sha256(b.encode()).digest()


# =========================
# FASTAPI INTEGRATION
# =========================

app = FastAPI(title="Session Monitoring Service")
session_monitor = SessionMonitor()


def get_session_id(request: Request) -> str:
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия отсутствует",
        )
    return session_id


def session_guard(
    request: Request,
    session_id: str = Depends(get_session_id),
) -> int:
    fingerprint = request.headers.get("User-Agent", "")
    client_ip = request.client.host if request.client else "0.0.0.0"

    return session_monitor.validate_session(
        session_id=session_id,
        current_ip=client_ip,
        fingerprint=fingerprint,
    )


# =========================
# PROTECTED ENDPOINT
# =========================

@app.get("/secure-area")
def secure_area(user_id: int = Depends(session_guard)) -> dict:
    return {"status": "ok", "user_id": user_id}


# =========================
# FORCE LOGOUT ENDPOINT
# =========================

@app.post("/sessions/{session_id}/terminate")
def terminate_session(session_id: str) -> dict:
    session_monitor.invalidate_session(session_id)
    return {"status": "terminated"}
