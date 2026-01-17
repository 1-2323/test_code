import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, Response, Request, HTTPException
from itsdangerous import URLSafeSerializer, BadSignature

class SessionProvider:
    """
    Менеджер сессий, обеспечивающий безопасность через подписанные куки.
    """

    def __init__(
        self, 
        secret_key: str, 
        session_name: str = "session_id",
        max_age: int = 3600,  # 1 час
        domain: Optional[str] = None
    ):
        self.serializer = URLSafeSerializer(secret_key)
        self.session_name = session_name
        self.max_age = max_age
        self.domain = domain

    def create_session(self, response: Response, user_id: int) -> str:
        """
        Создает подписанную сессионную куку.
        
        Параметры безопасности:
        - httponly: защита от XSS (JS не может прочитать куку).
        - samesite: защита от CSRF.
        - secure: передача только по HTTPS.
        """
        # Создаем полезную нагрузку
        payload = {
            "uid": user_id,
            "iat": datetime.now(timezone.utc).timestamp()
        }
        token = self.serializer.dumps(payload)

        response.set_cookie(
            key=self.session_name,
            value=token,
            max_age=self.max_age,
            expires=self.max_age,
            domain=self.domain,
            httponly=True,
            samesite="lax",
            secure=True  # Включать при наличии SSL
        )
        return token

    def get_session_data(self, request: Request) -> Optional[dict]:
        """
        Извлекает и проверяет подпись сессии из входящего запроса.
        """
        token = request.cookies.get(self.session_name)
        if not token:
            return None

        try:
            data = self.serializer.loads(token)
            return data
        except BadSignature:
            # Если кука была изменена клиентом
            return None

    def invalidate_session(self, response: Response):
        """
        Удаляет сессионную куку (Logout).
        """
        response.delete_cookie(
            key=self.session_name,
            domain=self.domain,
            httponly=True
        )

# --- Пример интеграции с FastAPI ---

app = FastAPI()
# В реальном приложении секретный ключ берется из .env
session_manager = SessionProvider(secret_key="SUPER_SECRET_KEY", max_age=1800)

@app.post("/login")
async def login(response: Response):
    # Логика проверки пароля опущена для краткости
    user_id = 123
    session_manager.create_session(response, user_id)
    return {"message": "Вход выполнен, сессия создана"}

@app.get("/me")
async def get_me(request: Request):
    data = session_manager.get_session_data(request)
    if not data:
        raise HTTPException(status_code=401, detail="Сессия не найдена или невалидна")
    return {"user_id": data["uid"]}

@app.post("/logout")
async def logout(response: Response):
    session_manager.invalidate_session(response)
    return {"message": "Сессия успешно завершена"}

if __name__ == "__main__":
    print("SessionProvider инициализирован.")