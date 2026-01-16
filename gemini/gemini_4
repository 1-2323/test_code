from enum import Enum
from typing import Optional, Dict, List
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, Field

# --- Перечисления и Модели ---

class UserRole(str, Enum):
    """Роли пользователей в системе."""
    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"


class User(BaseModel):
    """Модель пользователя."""
    id: int
    username: str
    role: UserRole


class Comment(BaseModel):
    """Модель комментария."""
    id: int
    text: str
    author_id: int
    is_hidden: bool = False
    is_deleted: bool = False


# --- Имитация базы данных ---

MOCK_COMMENTS_DB: Dict[int, Comment] = {
    1: Comment(id=1, text="Это отличный пост!", author_id=10),
    2: Comment(id=2, text="Здесь спам и реклама.", author_id=11),
    3: Comment(id=3, text="Неприемлемый контент.", author_id=12),
}


# --- Сервисный слой: Логика модерации ---

class CommentActions:
    """
    Класс-сервис для выполнения действий модерации над комментариями.
    Отвечает только за изменение состояния данных.
    """

    def __init__(self, db: Dict[int, Comment]):
        self.db = db

    def _get_comment(self, comment_id: int) -> Comment:
        """Вспомогательный метод для поиска комментария."""
        comment = self.db.get(comment_id)
        if not comment or comment.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Комментарий с ID {comment_id} не найден."
            )
        return comment

    def hide_comment(self, comment_id: int) -> Comment:
        """Скрывает комментарий из публичного доступа."""
        comment = self._get_comment(comment_id)
        comment.is_hidden = True
        return comment

    def delete_comment(self, comment_id: int) -> bool:
        """Помечает комментарий как удаленный."""
        comment = self._get_comment(comment_id)
        comment.is_deleted = True
        # В реальной БД здесь был бы comment.save() или commit()
        return True


# --- Зависимости (Dependency Injection) ---

async def get_current_user() -> User:
    """
    Имитация извлечения пользователя из токена.
    Для теста можно менять роль на UserRole.USER, чтобы увидеть ошибку 403.
    """
    return User(id=1, username="moder_pro", role=UserRole.MODERATOR)


def RoleChecker(allowed_roles: List[UserRole]):
    """
    Фабрика зависимостей для проверки ролей.
    """
    def _check(user: User = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия."
            )
        return user
    return _check


# --- API Эндпоинты ---

app = FastAPI(title="Moderation Service")
moderation_service = CommentActions(MOCK_COMMENTS_DB)

@app.patch(
    "/moderate/hide/{comment_id}",
    response_model=Comment,
    dependencies=[Depends(RoleChecker([UserRole.ADMIN, UserRole.MODERATOR]))]
)
async def hide_comment_endpoint(comment_id: int):
    """
    Эндпоинт для скрытия комментария. 
    Доступен только админам и модераторам.
    """
    return moderation_service.hide_comment(comment_id)


@app.delete(
    "/moderate/delete/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RoleChecker([UserRole.ADMIN]))]
)
async def delete_comment_endpoint(comment_id: int):
    """
    Эндпоинт для удаления комментария. 
    Доступен ТОЛЬКО администраторам.
    """
    moderation_service.delete_comment(comment_id)
    return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
