import logging
from typing import Dict

from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel


# =========================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# =========================
# МОДЕЛИ ПОЛЬЗОВАТЕЛЯ
# =========================

class User(BaseModel):
    """
    Модель пользователя системы.
    """
    id: int
    username: str
    role: str  # admin | moderator | user


def get_current_user() -> User:
    """
    Имитирует получение текущего пользователя из сессии.
    """
    return User(
        id=10,
        username="moderator_user",
        role="moderator",
    )


# =========================
# МОДЕЛЬ КОММЕНТАРИЯ
# =========================

class Comment(BaseModel):
    """
    Модель комментария.
    """
    id: int
    author_id: int
    content: str
    is_hidden: bool = False
    is_deleted: bool = False


# =========================
# ХРАНИЛИЩЕ КОММЕНТАРИЕВ
# =========================

class CommentRepository:
    """
    Простейшее хранилище комментариев (in-memory).
    """

    def __init__(self) -> None:
        self._comments: Dict[int, Comment] = {}

    def get_by_id(self, comment_id: int) -> Comment:
        """
        Возвращает комментарий по ID.
        """
        comment = self._comments.get(comment_id)

        if comment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Комментарий не найден",
            )

        return comment

    def save(self, comment: Comment) -> None:
        """
        Сохраняет комментарий.
        """
        self._comments[comment.id] = comment

    def seed(self) -> None:
        """
        Добавляет тестовые данные.
        """
        self.save(
            Comment(
                id=1,
                author_id=5,
                content="Первый комментарий",
            )
        )
        self.save(
            Comment(
                id=2,
                author_id=6,
                content="Второй комментарий",
            )
        )


# =========================
# БИЗНЕС-ЛОГИКА МОДЕРАЦИИ
# =========================

class CommentActions:
    """
    Класс, инкапсулирующий действия модерации комментариев.
    """

    def __init__(self, repository: CommentRepository) -> None:
        self._repository: CommentRepository = repository

    def delete_comment(self, comment_id: int, user: User) -> None:
        """
        Удаляет комментарий после проверки прав.
        """
        self._check_permissions(user)

        comment: Comment = self._repository.get_by_id(comment_id)
        comment.is_deleted = True

        self._repository.save(comment)

        self._log_action(
            action="DELETE",
            comment_id=comment_id,
            user=user,
        )

    def hide_comment(self, comment_id: int, user: User) -> None:
        """
        Скрывает комментарий после проверки прав.
        """
        self._check_permissions(user)

        comment: Comment = self._repository.get_by_id(comment_id)
        comment.is_hidden = True

        self._repository.save(comment)

        self._log_action(
            action="HIDE",
            comment_id=comment_id,
            user=user,
        )

    def _check_permissions(self, user: User) -> None:
        """
        Проверяет, что пользователь является
        администратором или модератором.
        """
        if user.role not in {"admin", "moderator"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для модерации комментариев",
            )

    def _log_action(self, action: str, comment_id: int, user: User) -> None:
        """
        Логирует операцию модерации.
        """
        logger.info(
            "ACTION=%s | COMMENT_ID=%s | PERFORMED_BY=%s (id=%s)",
            action,
            comment_id,
            user.username,
            user.id,
        )


# =========================
# FASTAPI ПРИЛОЖЕНИЕ
# =========================

app = FastAPI(
    title="Comment Moderation Service",
    version="1.0.0",
    description="Сервис модерации комментариев",
)

comment_repository = CommentRepository()
comment_repository.seed()

comment_actions = CommentActions(comment_repository)


# =========================
# ENDPOINTS
# =========================

@app.post(
    "/comments/{comment_id}/delete",
    summary="Удалить комментарий",
)
def delete_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Эндпоинт удаления комментария.
    """
    comment_actions.delete_comment(
        comment_id=comment_id,
        user=current_user,
    )

    return {"status": "Комментарий удалён"}


@app.post(
    "/comments/{comment_id}/hide",
    summary="Скрыть комментарий",
)
def hide_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Эндпоинт скрытия комментария.
    """
    comment_actions.hide_comment(
        comment_id=comment_id,
        user=current_user,
    )

    return {"status": "Комментарий скрыт"}
