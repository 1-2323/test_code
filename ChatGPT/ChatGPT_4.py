from enum import Enum
from typing import Dict, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel


# =========================
# Доменные модели
# =========================

class UserRole(str, Enum):
    """
    Допустимые роли пользователя.
    """
    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"


class User(BaseModel):
    """
    Модель текущего пользователя.
    """
    id: int
    username: str
    role: UserRole


class Comment(BaseModel):
    """
    Модель комментария.
    """
    id: int
    text: str
    is_hidden: bool


# =========================
# Имитация базы данных
# =========================

class FakeCommentDatabase:
    """
    Упрощённая in-memory база комментариев.
    """

    def __init__(self) -> None:
        self._comments: Dict[int, Comment] = {
            1: Comment(id=1, text="Nice post!", is_hidden=False),
            2: Comment(id=2, text="Spam comment", is_hidden=False),
        }

    def get_by_id(self, comment_id: int) -> Optional[Comment]:
        """
        Возвращает комментарий по ID.
        """
        return self._comments.get(comment_id)

    def delete(self, comment_id: int) -> None:
        """
        Удаляет комментарий.
        """
        del self._comments[comment_id]

    def save(self, comment: Comment) -> None:
        """
        Сохраняет изменения комментария.
        """
        self._comments[comment.id] = comment


# =========================
# Бизнес-логика
# =========================

class CommentActions:
    """
    Класс, инкапсулирующий действия модерации комментариев.
    """

    def __init__(self, database: FakeCommentDatabase) -> None:
        self._database: FakeCommentDatabase = database

    def delete_comment(self, comment_id: int) -> None:
        """
        Удаляет комментарий по ID.
        """
        comment: Optional[Comment] = self._get_comment(comment_id)
        self._database.delete(comment.id)

    def hide_comment(self, comment_id: int) -> Comment:
        """
        Скрывает комментарий.
        """
        comment: Optional[Comment] = self._get_comment(comment_id)
        comment.is_hidden = True
        self._database.save(comment)
        return comment

    def _get_comment(self, comment_id: int) -> Comment:
        """
        Возвращает комментарий или выбрасывает исключение.
        """
        comment: Optional[Comment] = self._database.get_by_id(comment_id)

        if comment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comment not found",
            )

        return comment


# =========================
# Авторизация и зависимости
# =========================

def get_current_user() -> User:
    """
    Имитация получения пользователя из сессии.
    """
    return User(
        id=1,
        username="moderator_user",
        role=UserRole.MODERATOR,
    )


def require_moderation_role(user: User) -> None:
    """
    Проверяет, что пользователь имеет права модерации.
    """
    if user.role not in {UserRole.ADMIN, UserRole.MODERATOR}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


def get_comment_actions() -> CommentActions:
    """
    Dependency для CommentActions.
    """
    database = FakeCommentDatabase()
    return CommentActions(database=database)


# =========================
# FastAPI-приложение
# =========================

app = FastAPI(title="Comment Moderation Service")


@app.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
    actions: CommentActions = Depends(get_comment_actions),
) -> dict:
    """
    Эндпоинт удаления комментария.
    """
    require_moderation_role(current_user)
    actions.delete_comment(comment_id)
    return {"status": "deleted"}


@app.patch("/comments/{comment_id}/hide", response_model=Comment)
def hide_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
    actions: CommentActions = Depends(get_comment_actions),
) -> Comment:
    """
    Эндпоинт скрытия комментария.
    """
    require_moderation_role(current_user)
    return actions.hide_comment(comment_id)
