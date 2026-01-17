import logging
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Final, Optional
from fastapi import FastAPI, HTTPException, Request, status, Depends
from pydantic import BaseModel, Field

# --- Настройка логирования ---
# Настраиваем формат для отслеживания действий модераторов
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | MODERATION | %(levelname)s | %(message)s'
)
logger = logging.getLogger("moderation_service")

# --- Модели данных ---

class UserRole(str, Enum):
    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"

class UserInfo(BaseModel):
    id: int
    username: str
    role: UserRole

class ModerationActionResponse(BaseModel):
    status: str
    comment_id: int
    action_performed: str
    moderator: str
    timestamp: datetime

# --- Ядро логики модерации ---

class CommentActions:
    """
    Класс, отвечающий за выполнение действий над комментариями.
    Включает встроенную проверку прав и обязательное логирование.
    """

    def __init__(self) -> None:
        # Имитация хранилища комментариев (ID: {текст, статус})
        self._comments_db: Dict[int, Dict[str, Any]] = {
            101: {"text": "Hello world", "is_hidden": False},
            102: {"text": "Some spam content", "is_hidden": False}
        }
        self.ALLOWED_ROLES: Final[set[UserRole]] = {UserRole.ADMIN, UserRole.MODERATOR}

    def _validate_permissions(self, user: UserInfo) -> None:
        """Внутренняя проверка прав доступа перед выполнением действия."""
        if user.role not in self.ALLOWED_ROLES:
            logger.warning(f"Unauthorized access attempt by user {user.username} (Role: {user.role})")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions to perform moderation actions."
            )

    def delete_comment(self, comment_id: int, moderator: UserInfo) -> bool:
        """
        Полное удаление комментария из базы данных.
        """
        self._validate_permissions(moderator)

        if comment_id not in self._comments_db:
            raise HTTPException(status_code=404, detail="Comment not found")

        del self._comments_db[comment_id]
        
        logger.info(
            f"ACTION: DELETE | COMMENT_ID: {comment_id} | BY: {moderator.username} (ID: {moderator.id})"
        )
        return True

    def hide_comment(self, comment_id: int, moderator: UserInfo) -> bool:
        """
        Скрытие комментария (soft delete / moderation hide).
        """
        self._validate_permissions(moderator)

        if comment_id not in self._comments_db:
            raise HTTPException(status_code=404, detail="Comment not found")

        self._comments_db[comment_id]["is_hidden"] = True
        
        logger.info(
            f"ACTION: HIDE | COMMENT_ID: {comment_id} | BY: {moderator.username} (ID: {moderator.id})"
        )
        return True

# --- API и зависимости ---

app = FastAPI(title="Comment Moderation API")
moderation_service = CommentActions()

async def get_current_moderator() -> UserInfo:
    """
    Имитация получения пользователя из токена авторизации.
    Для теста возвращает пользователя с ролью MODERATOR.
    """
    return UserInfo(id=7, username="mod_alex", role=UserRole.MODERATOR)

@app.delete("/moderation/comments/{comment_id}", response_model=ModerationActionResponse)
async def delete_comment_endpoint(
    comment_id: int, 
    current_user: UserInfo = Depends(get_current_moderator)
) -> ModerationActionResponse:
    """Эндпоинт для окончательного удаления комментария."""
    moderation_service.delete_comment(comment_id, current_user)
    
    return ModerationActionResponse(
        status="success",
        comment_id=comment_id,
        action_performed="DELETE",
        moderator=current_user.username,
        timestamp=datetime.now()
    )

@app.patch("/moderation/comments/{comment_id}/hide", response_model=ModerationActionResponse)
async def hide_comment_endpoint(
    comment_id: int,
    current_user: UserInfo = Depends(get_current_moderator)
) -> ModerationActionResponse:
    """Эндпоинт для скрытия комментария от публичного просмотра."""
    moderation_service.hide_comment(comment_id, current_user)
    
    return ModerationActionResponse(
        status="success",
        comment_id=comment_id,
        action_performed="HIDE",
        moderator=current_user.username,
        timestamp=datetime.now()
    )