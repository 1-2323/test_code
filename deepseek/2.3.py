import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models import User, PasswordResetToken
from config import settings
from utils.email_service import send_password_reset_email

router = APIRouter()


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetResponse(BaseModel):
    message: str
    token_expires_at: Optional[datetime] = None


def generate_reset_token(length: int = 32) -> str:
    """Генерирует случайный токен для сброса пароля"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@router.post(
    "/password-reset/request",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Запрос на сброс пароля",
    description="Принимает email пользователя, генерирует токен и отправляет ссылку для сброса пароля"
)
async def request_password_reset(
    request: PasswordResetRequest,
    db: Session = Depends(get_db)
) -> PasswordResetResponse:
    """
    Обрабатывает запрос на сброс пароля.
    
    Args:
        request: Объект с email пользователя
        db: Сессия базы данных
        
    Returns:
        Ответ с сообщением об успешной отправке ссылки
    """
    try:
        # Поиск пользователя по email
        user = db.query(User).filter(
            User.email == request.email,
            User.is_active == True
        ).first()
        
        # Если пользователь не найден, всё равно возвращаем успех (security best practice)
        if not user:
            return PasswordResetResponse(
                message="Если пользователь с таким email существует, на него будет отправлена ссылка для сброса пароля"
            )
        
        # Создание токена сброса пароля
        token = generate_reset_token()
        expires_at = datetime.utcnow() + timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS)
        
        # Сохранение токена в базе данных
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=expires_at,
            is_used=False
        )
        
        db.add(reset_token)
        db.commit()
        db.refresh(reset_token)
        
        # Формирование ссылки для сброса пароля
        reset_link = f"{settings.FRONTEND_URL}/password-reset/confirm?token={token}"
        
        # Отправка email с ссылкой
        await send_password_reset_email(
            to_email=user.email,
            username=user.username,
            reset_link=reset_link,
            expires_hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS
        )
        
        return PasswordResetResponse(
            message="Ссылка для сброса пароля отправлена на указанный email",
            token_expires_at=expires_at
        )
        
    except Exception as e:
        # Логирование ошибки
        logger.error(f"Ошибка при запросе сброса пароля для email {request.email}: {str(e)}")
        
        # В продакшене возвращаем общее сообщение об ошибке
        if settings.DEBUG:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Произошла ошибка при обработке запроса: {str(e)}"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."
            )