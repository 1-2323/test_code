import secrets
from datetime import timedelta
from typing import Optional

import redis
from fastapi import Response, HTTPException, status

# =========================
# CONFIGURATION
# =========================

REDIS_URL = "redis://localhost:6379/0"

SESSION_COOKIE_NAME = "session_id"
SESSION_TTL_SECONDS = 60 * 60  # 1 hour
PASSWORD_FLOW_TTL_SECONDS = 10 * 60  # 10 minutes

SESSION_DOMAIN = "example.com"

# =========================
# REDIS CLIENT
# =========================

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)

# =========================
# SESSION PROVIDER
# =========================

class SessionProvider:
    """
    Менеджер пользовательских сессий.
    """

    def create_session(
        self,
        *,
        response: Response,
        user_id: int,
    ) -> str:
        session_token = self._generate_token()
        redis_client.setex(
            self._session_key(session_token),
            SESSION_TTL_SECONDS,
            user_id,
        )

        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_token,
            max_age=SESSION_TTL_SECONDS,
            expires=SESSION_TTL_SECONDS,
            domain=SESSION_DOMAIN,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )

        return session_token

    def invalidate_session(
        self,
        *,
        response: Response,
        session_token: Optional[str],
    ) -> None:
        if session_token:
            redis_client.delete(self._session_key(session_token))

        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            domain=SESSION_DOMAIN,
            path="/",
        )

    def validate_session(self, session_token: str) -> int:
        user_id = redis_client.get(self._session_key(session_token))
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Сессия недействительна",
            )
        return int(user_id)

    # =========================
    # PASSWORD CHANGE FLOW
    # =========================

    def create_password_change_token(self, user_id: int) -> str:
        token = self._generate_token()
        redis_client.setex(
            self._password_flow_key(token),
            PASSWORD_FLOW_TTL_SECONDS,
            user_id,
        )
        return token

    def consume_password_change_token(self, token: str) -> int:
        """
        Токен используется строго один раз.
        """
        key = self._password_flow_key(token)
        user_id = redis_client.get(key)

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Токен недействителен или истёк",
            )

        redis_client.delete(key)
        return int(user_id)

    # =========================
    # INTERNAL UTILITIES
    # =========================

    def _generate_token(self) -> str:
        """
        Криптографически стойкий одноразовый токен.
        """
        return secrets.token_urlsafe(48)

    def _session_key(self, token: str) -> str:
        return f"session:{token}"

    def _password_flow_key(self, token: str) -> str:
        return f"password-flow:{token}"
