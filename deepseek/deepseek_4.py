"""
Модуль модерации комментариев с проверкой ролей пользователей и действиями над комментариями.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Depends, status, Body, Path
from pydantic import BaseModel, Field, validator
import sqlite3


# ==================== МОДЕЛИ ДАННЫХ ====================

class UserRole(str, Enum):
    """Роли пользователей для системы модерации."""
    ADMIN = "admin"
    MODERATOR = "moderator"
    EDITOR = "editor"
    USER = "user"
    GUEST = "guest"


class CommentStatus(str, Enum):
    """Статусы комментариев."""
    PUBLISHED = "published"
    HIDDEN = "hidden"
    DELETED = "deleted"
    PENDING = "pending"
    FLAGGED = "flagged"


class Comment(BaseModel):
    """Модель комментария."""
    id: int = Field(..., gt=0, description="Уникальный идентификатор комментария")
    user_id: int = Field(..., gt=0, description="ID автора комментария")
    content: str = Field(..., min_length=1, max_length=1000, description="Текст комментария")
    article_id: int = Field(..., gt=0, description="ID статьи/поста")
    status: CommentStatus = Field(CommentStatus.PUBLISHED, description="Текущий статус комментария")
    created_at: datetime = Field(default_factory=datetime.now, description="Время создания")
    updated_at: Optional[datetime] = Field(None, description="Время последнего обновления")
    deleted_at: Optional[datetime] = Field(None, description="Время удаления (мягкое удаление)")
    moderated_by: Optional[int] = Field(None, description="ID модератора/администратора")
    moderation_reason: Optional[str] = Field(None, max_length=500, description="Причина модерации")
    
    @validator('content')
    def validate_content(cls, v):
        """Валидация содержания комментария."""
        # Проверка на недопустимые слова (упрощенная версия)
        forbidden_words = ['спам', 'оскорбление', 'реклама']
        for word in forbidden_words:
            if word in v.lower():
                raise ValueError(f"Комментарий содержит недопустимое слово: {word}")
        return v
    
    class Config:
        """Конфигурация Pydantic модели."""
        schema_extra = {
            "example": {
                "id": 1,
                "user_id": 123,
                "content": "Отличная статья, спасибо автору!",
                "article_id": 456,
                "status": "published",
                "created_at": "2024-01-15T10:30:00",
                "updated_at": None
            }
        }


class ModerationAction(str, Enum):
    """Действия модерации."""
    DELETE = "delete"
    HIDE = "hide"
    RESTORE = "restore"
    APPROVE = "approve"
    FLAG = "flag"


class ModerationRequest(BaseModel):
    """Модель запроса на модерацию."""
    action: ModerationAction = Field(..., description="Действие модерации")
    reason: Optional[str] = Field(None, max_length=500, description="Причина действия")
    permanent: bool = Field(False, description="Постоянное удаление (без возможности восстановления)")
    
    class Config:
        """Конфигурация Pydantic модели."""
        schema_extra = {
            "example": {
                "action": "hide",
                "reason": "Комментарий нарушает правила сообщества",
                "permanent": False
            }
        }


class ModerationResponse(BaseModel):
    """Модель ответа на действие модерации."""
    success: bool = Field(..., description="Успешно ли выполнено действие")
    comment_id: int = Field(..., description="ID комментария")
    action: ModerationAction = Field(..., description="Выполненное действие")
    new_status: CommentStatus = Field(..., description="Новый статус комментария")
    message: str = Field(..., description="Сообщение о результате")
    timestamp: datetime = Field(default_factory=datetime.now, description="Время выполнения")
    
    class Config:
        """Конфигурация Pydantic модели."""
        schema_extra = {
            "example": {
                "success": True,
                "comment_id": 1,
                "action": "hide",
                "new_status": "hidden",
                "message": "Комментарий успешно скрыт",
                "timestamp": "2024-01-15T11:00:00"
            }
        }


# ==================== СЛУЖЕБНЫЕ КЛАССЫ ====================

@dataclass
class CurrentUser:
    """Модель текущего пользователя."""
    id: int
    username: str
    role: UserRole
    email: Optional[str] = None
    is_active: bool = True


class CommentDatabase:
    """Класс для работы с базой данных комментариев."""
    
    def __init__(self, db_path: str = "comments.db"):
        """
        Инициализация подключения к БД.
        
        Args:
            db_path: Путь к файлу базы данных.
        """
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self) -> None:
        """Инициализирует таблицы базы данных."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица комментариев
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    article_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    deleted_at TIMESTAMP,
                    moderated_by INTEGER,
                    moderation_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (moderated_by) REFERENCES users (id)
                )
            ''')
            
            # Таблица пользователей (упрощенная)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL DEFAULT 'user',
                    email TEXT,
                    is_active BOOLEAN DEFAULT 1
                )
            ''')
            
            conn.commit()
    
    def get_comment_by_id(self, comment_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает комментарий по ID.
        
        Args:
            comment_id: ID комментария.
            
        Returns:
            Словарь с данными комментария или None.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM comments WHERE id = ? AND deleted_at IS NULL",
                (comment_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_comment_status(
        self,
        comment_id: int,
        new_status: CommentStatus,
        moderator_id: Optional[int] = None,
        reason: Optional[str] = None,
        permanent: bool = False
    ) -> bool:
        """
        Обновляет статус комментария.
        
        Args:
            comment_id: ID комментария.
            new_status: Новый статус.
            moderator_id: ID модератора (если есть).
            reason: Причина изменения статуса.
            permanent: Флаг постоянного удаления.
            
        Returns:
            bool: True если обновление успешно.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            update_fields = {
                "status": new_status.value,
                "updated_at": datetime.now().isoformat()
            }
            
            # Для удаления устанавливаем deleted_at
            if new_status == CommentStatus.DELETED:
                update_fields["deleted_at"] = datetime.now().isoformat()
            
            # Для восстановления очищаем deleted_at
            if new_status == CommentStatus.PUBLISHED:
                update_fields["deleted_at"] = None
            
            # Если указан модератор, сохраняем информацию
            if moderator_id:
                update_fields["moderated_by"] = moderator_id
                if reason:
                    update_fields["moderation_reason"] = reason
            
            # Формируем SQL запрос
            set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
            values = list(update_fields.values())
            values.append(comment_id)
            
            query = f"UPDATE comments SET {set_clause} WHERE id = ?"
            
            if permanent and new_status == CommentStatus.DELETED:
                # Полное удаление записи из БД
                cursor.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
            else:
                cursor.execute(query, values)
            
            conn.commit()
            return cursor.rowcount > 0


class PermissionError(Exception):
    """Исключение для ошибок прав доступа."""
    pass


class CommentNotFoundError(Exception):
    """Исключение для случая, когда комментарий не найден."""
    pass


class ModerationError(Exception):
    """Исключение для ошибок модерации."""
    pass


class CommentActions:
    """
    Класс для выполнения действий модерации над комментариями.
    """
    
    def __init__(self, db: CommentDatabase):
        """
        Инициализация класса действий.
        
        Args:
            db: Объект для работы с базой данных комментариев.
        """
        self.db = db
    
    def _check_moderator_permissions(self, user: CurrentUser) -> None:
        """
        Проверяет права пользователя на модерацию.
        
        Args:
            user: Текущий пользователь.
            
        Raises:
            PermissionError: Если у пользователя недостаточно прав.
        """
        # Только админы и модераторы могут модерировать комментарии
        allowed_roles = {UserRole.ADMIN, UserRole.MODERATOR}
        
        if user.role not in allowed_roles:
            raise PermissionError(
                f"Недостаточно прав. Требуется роль: {', '.join(allowed_roles)}"
            )
        
        if not user.is_active:
            raise PermissionError("Учетная запись пользователя неактивна")
    
    def _validate_action_for_status(
        self,
        current_status: CommentStatus,
        action: ModerationAction
    ) -> None:
        """
        Проверяет, допустимо ли действие для текущего статуса комментария.
        
        Args:
            current_status: Текущий статус комментария.
            action: Запрошенное действие.
            
        Raises:
            ModerationError: Если действие недопустимо для текущего статуса.
        """
        # Матрица допустимых действий для каждого статуса
        allowed_actions = {
            CommentStatus.PUBLISHED: {
                ModerationAction.HIDE,
                ModerationAction.DELETE,
                ModerationAction.FLAG
            },
            CommentStatus.HIDDEN: {
                ModerationAction.RESTORE,
                ModerationAction.DELETE
            },
            CommentStatus.PENDING: {
                ModerationAction.APPROVE,
                ModerationAction.DELETE
            },
            CommentStatus.FLAGGED: {
                ModerationAction.HIDE,
                ModerationAction.DELETE,
                ModerationAction.RESTORE
            },
            CommentStatus.DELETED: {
                ModerationAction.RESTORE
            }
        }
        
        if action not in allowed_actions.get(current_status, set()):
            raise ModerationError(
                f"Действие '{action.value}' недопустимо для статуса '{current_status.value}'"
            )
    
    def delete_comment(
        self,
        comment_id: int,
        user: CurrentUser,
        reason: Optional[str] = None,
        permanent: bool = False
    ) -> ModerationResponse:
        """
        Удаляет комментарий (мягкое или постоянное удаление).
        
        Args:
            comment_id: ID комментария.
            user: Пользователь, выполняющий действие.
            reason: Причина удаления.
            permanent: Флаг постоянного удаления.
            
        Returns:
            ModerationResponse: Результат операции.
            
        Raises:
            PermissionError: Если недостаточно прав.
            CommentNotFoundError: Если комментарий не найден.
            ModerationError: Если действие недопустимо.
        """
        try:
            # Проверяем права
            self._check_moderator_permissions(user)
            
            # Получаем комментарий
            comment_data = self.db.get_comment_by_id(comment_id)
            if not comment_data:
                raise CommentNotFoundError(f"Комментарий с ID {comment_id} не найден")
            
            # Определяем текущий статус
            current_status = CommentStatus(comment_data['status'])
            
            # Проверяем допустимость действия
            self._validate_action_for_status(current_status, ModerationAction.DELETE)
            
            # Определяем новый статус
            new_status = CommentStatus.DELETED
            
            # Выполняем удаление
            success = self.db.update_comment_status(
                comment_id=comment_id,
                new_status=new_status,
                moderator_id=user.id,
                reason=reason,
                permanent=permanent
            )
            
            if not success:
                raise ModerationError("Не удалось удалить комментарий")
            
            return ModerationResponse(
                success=True,
                comment_id=comment_id,
                action=ModerationAction.DELETE,
                new_status=new_status,
                message=f"Комментарий {'полностью удален' if permanent else 'удален'}"
            )
            
        except (PermissionError, CommentNotFoundError, ModerationError) as e:
            # Повторно вызываем исключения для обработки на уровне API
            raise
        except Exception as e:
            raise ModerationError(f"Ошибка при удалении комментария: {str(e)}")
    
    def hide_comment(
        self,
        comment_id: int,
        user: CurrentUser,
        reason: Optional[str] = None
    ) -> ModerationResponse:
        """
        Скрывает комментарий от публичного просмотра.
        
        Args:
            comment_id: ID комментария.
            user: Пользователь, выполняющий действие.
            reason: Причина скрытия.
            
        Returns:
            ModerationResponse: Результат операции.
            
        Raises:
            PermissionError: Если недостаточно прав.
            CommentNotFoundError: Если комментарий не найден.
            ModerationError: Если действие недопустимо.
        """
        try:
            # Проверяем права
            self._check_moderator_permissions(user)
            
            # Получаем комментарий
            comment_data = self.db.get_comment_by_id(comment_id)
            if not comment_data:
                raise CommentNotFoundError(f"Комментарий с ID {comment_id} не найден")
            
            # Определяем текущий статус
            current_status = CommentStatus(comment_data['status'])
            
            # Проверяем допустимость действия
            self._validate_action_for_status(current_status, ModerationAction.HIDE)
            
            # Определяем новый статус
            new_status = CommentStatus.HIDDEN
            
            # Выполняем скрытие
            success = self.db.update_comment_status(
                comment_id=comment_id,
                new_status=new_status,
                moderator_id=user.id,
                reason=reason
            )
            
            if not success:
                raise ModerationError("Не удалось скрыть комментарий")
            
            return ModerationResponse(
                success=True,
                comment_id=comment_id,
                action=ModerationAction.HIDE,
                new_status=new_status,
                message="Комментарий успешно скрыт"
            )
            
        except (PermissionError, CommentNotFoundError, ModerationError) as e:
            raise
        except Exception as e:
            raise ModerationError(f"Ошибка при скрытии комментария: {str(e)}")
    
    def restore_comment(
        self,
        comment_id: int,
        user: CurrentUser,
        reason: Optional[str] = None
    ) -> ModerationResponse:
        """
        Восстанавливает скрытый или удаленный комментарий.
        
        Args:
            comment_id: ID комментария.
            user: Пользователь, выполняющий действие.
            reason: Причина восстановления.
            
        Returns:
            ModerationResponse: Результат операции.
        """
        try:
            self._check_moderator_permissions(user)
            
            # Получаем комментарий (включая удаленные)
            with sqlite3.connect(self.db.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM comments WHERE id = ?", (comment_id,))
                row = cursor.fetchone()
                
            if not row:
                raise CommentNotFoundError(f"Комментарий с ID {comment_id} не найден")
            
            comment_data = dict(row)
            current_status = CommentStatus(comment_data['status'])
            
            self._validate_action_for_status(current_status, ModerationAction.RESTORE)
            
            new_status = CommentStatus.PUBLISHED
            
            success = self.db.update_comment_status(
                comment_id=comment_id,
                new_status=new_status,
                moderator_id=user.id,
                reason=reason
            )
            
            if not success:
                raise ModerationError("Не удалось восстановить комментарий")
            
            return ModerationResponse(
                success=True,
                comment_id=comment_id,
                action=ModerationAction.RESTORE,
                new_status=new_status,
                message="Комментарий успешно восстановлен"
            )
            
        except (PermissionError, CommentNotFoundError, ModerationError) as e:
            raise
        except Exception as e:
            raise ModerationError(f"Ошибка при восстановлении комментария: {str(e)}")


# ==================== FASTAPI ЗАВИСИМОСТИ ====================

def get_current_user() -> CurrentUser:
    """
    Зависимость для получения текущего пользователя.
    В реальном приложении здесь была бы JWT-аутентификация.
    """
    # Имитация модератора
    return CurrentUser(
        id=2,
        username="moderator_john",
        role=UserRole.MODERATOR,
        email="moderator@example.com"
    )


def get_comment_db() -> CommentDatabase:
    """Зависимость для получения базы данных комментариев."""
    return CommentDatabase()


def get_comment_actions(
    db: CommentDatabase = Depends(get_comment_db)
) -> CommentActions:
    """Зависимость для получения экземпляра CommentActions."""
    return CommentActions(db)


# ==================== FASTAPI ПРИЛОЖЕНИЕ ====================

app = FastAPI(
    title="Comment Moderation API",
    description="API для модерации комментариев с проверкой ролей пользователей",
    version="1.0.0"
)


@app.get("/")
async def root():
    """Корневой эндпоинт."""
    return {
        "service": "Comment Moderation System",
        "version": "1.0.0",
        "endpoints": {
            "moderate_comment": "/api/comments/{comment_id}/moderate (POST)",
            "health": "/health"
        }
    }


@app.get("/health")
async def health_check():
    """Проверка здоровья сервиса."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "comment_moderation"
    }


@app.post(
    "/api/comments/{comment_id}/moderate",
    response_model=ModerationResponse,
    summary="Выполнить действие модерации",
    description="""
    Выполняет действие модерации над комментарием.
    Требуются права администратора или модератора.
    Доступные действия: delete, hide, restore, approve, flag.
    """,
    responses={
        200: {"description": "Действие выполнено успешно"},
        403: {"description": "Недостаточно прав"},
        404: {"description": "Комментарий не найден"},
        400: {"description": "Недопустимое действие или данные"}
    }
)
async def moderate_comment(
    comment_id: int = Path(..., gt=0, description="ID комментария для модерации"),
    moderation_request: ModerationRequest = Body(..., description="Данные для модерации"),
    current_user: CurrentUser = Depends(get_current_user),
    comment_actions: CommentActions = Depends(get_comment_actions)
) -> ModerationResponse:
    """
    Основной эндпоинт для модерации комментариев.
    
    Args:
        comment_id: ID комментария для модерации.
        moderation_request: Запрос на модерацию с действием и параметрами.
        current_user: Текущий пользователь (проверка роли).
        comment_actions: Экземпляр класса для выполнения действий.
        
    Returns:
        ModerationResponse: Результат выполнения действия модерации.
        
    Raises:
        HTTPException: При ошибках прав доступа, валидации или внутренних ошибках.
    """
    try:
        # Выбираем метод в зависимости от запрошенного действия
        action_handlers = {
            ModerationAction.DELETE: comment_actions.delete_comment,
            ModerationAction.HIDE: comment_actions.hide_comment,
            ModerationAction.RESTORE: comment_actions.restore_comment
        }
        
        handler = action_handlers.get(moderation_request.action)
        
        if not handler:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Действие '{moderation_request.action.value}' не реализовано"
            )
        
        # Вызываем соответствующий метод
        if moderation_request.action == ModerationAction.DELETE:
            result = handler(
                comment_id=comment_id,
                user=current_user,
                reason=moderation_request.reason,
                permanent=moderation_request.permanent
            )
        else:
            result = handler(
                comment_id=comment_id,
                user=current_user,
                reason=moderation_request.reason
            )
        
        return result
        
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except CommentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ModerationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Внутренняя ошибка при модерации комментария {comment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )


@app.get(
    "/api/comments/{comment_id}",
    summary="Получить информацию о комментарии",
    description="Возвращает информацию о комментарии по его ID.",
    responses={
        200: {"description": "Информация о комментарии"},
        404: {"description": "Комментарий не найден"}
    }
)
async def get_comment(
    comment_id: int = Path(..., gt=0, description="ID комментария"),
    db: CommentDatabase = Depends(get_comment_db)
):
    """
    Получает информацию о комментарии.
    
    Args:
        comment_id: ID комментария.
        db: База данных комментариев.
        
    Returns:
        Информация о комментарии.
    """
    comment_data = db.get_comment_by_id(comment_id)
    
    if not comment_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Комментарий с ID {comment_id} не найден"
        )
    
    return {
        "success": True,
        "comment": comment_data
    }


# Пример запуска приложения
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)