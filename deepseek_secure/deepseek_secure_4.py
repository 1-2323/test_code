from fastapi import FastAPI, HTTPException, Depends, status, Request
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import sqlite3
from contextlib import contextmanager
import logging
from uuid import UUID
import sys

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('moderation.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Comment Moderation API")

# --- Модели данных ---
class UserRole(str, Enum):
    """Роли пользователей для модерации."""
    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"
    GUEST = "guest"

class CommentStatus(str, Enum):
    """Статусы комментариев."""
    PUBLISHED = "published"
    HIDDEN = "hidden"
    DELETED = "deleted"
    PENDING = "pending"

class CommentAction(str, Enum):
    """Действия модерации."""
    DELETE = "delete"
    HIDE = "hide"
    RESTORE = "restore"

class ModerationLog(BaseModel):
    """Модель лога модерации."""
    id: int
    comment_id: int
    action: CommentAction
    performed_by: str
    performed_at: datetime
    reason: Optional[str] = None
    previous_status: Optional[CommentStatus] = None
    new_status: Optional[CommentStatus] = None

# --- Имитация аутентификации ---
class CurrentUser:
    """Класс для имитации текущего пользователя."""
    
    def __init__(self, user_id: int = 1, username: str = "moderator", role: UserRole = UserRole.MODERATOR):
        self.user_id = user_id
        self.username = username
        self.role = role
    
    def has_moderation_permission(self) -> bool:
        """Проверка прав на модерацию."""
        return self.role in [UserRole.ADMIN, UserRole.MODERATOR]

def get_current_user(request: Request) -> CurrentUser:
    """
    Зависимость для получения текущего пользователя.
    В реальном приложении - проверка JWT/сессии.
    """
    # Имитация получения из заголовков
    user_id = int(request.headers.get("X-User-Id", "1"))
    username = request.headers.get("X-Username", "moderator")
    role_str = request.headers.get("X-User-Role", UserRole.MODERATOR)
    
    try:
        role = UserRole(role_str)
    except ValueError:
        role = UserRole.USER
    
    return CurrentUser(user_id=user_id, username=username, role=role)

# --- Database Layer ---
class DatabaseManager:
    """Менеджер для работы с базой данных."""
    
    def __init__(self, db_path: str = "comments.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица комментариев
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    author_id INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    post_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'published',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hidden_reason TEXT
                )
            """)
            
            # Таблица логов модерации
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS moderation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comment_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    performed_by TEXT NOT NULL,
                    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reason TEXT,
                    previous_status TEXT,
                    new_status TEXT,
                    FOREIGN KEY (comment_id) REFERENCES comments(id)
                )
            """)
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для подключения к БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

# --- Core Moderation Logic ---
class CommentActions:
    """Класс для действий модерации комментариев."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def _log_moderation_action(
        self, 
        comment_id: int, 
        action: CommentAction, 
        performer: str,
        reason: Optional[str],
        previous_status: CommentStatus,
        new_status: CommentStatus
    ) -> None:
        """
        Логирование действия модерации.
        
        Args:
            comment_id: ID комментария
            action: Выполненное действие
            performer: Имя исполнителя
            reason: Причина действия
            previous_status: Предыдущий статус
            new_status: Новый статус
        """
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO moderation_logs 
                    (comment_id, action, performed_by, reason, previous_status, new_status)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (comment_id, action, performer, reason, previous_status, new_status))
                conn.commit()
                
                # Также логируем в файл
                log_message = (
                    f"Moderation Action: {action.value} | "
                    f"Comment: {comment_id} | "
                    f"Performer: {performer} | "
                    f"Status: {previous_status} -> {new_status} | "
                    f"Reason: {reason or 'N/A'}"
                )
                logger.info(log_message)
                
        except Exception as e:
            logger.error(f"Failed to log moderation action: {e}")
    
    def _get_comment(self, comment_id: int) -> Optional[Dict[str, Any]]:
        """Получение комментария по ID."""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM comments WHERE id = ?
            """, (comment_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def _update_comment_status(
        self, 
        comment_id: int, 
        new_status: CommentStatus, 
        hidden_reason: Optional[str] = None
    ) -> bool:
        """Обновление статуса комментария."""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE comments 
                    SET status = ?, 
                        hidden_reason = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_status.value, hidden_reason, comment_id))
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Failed to update comment status: {e}")
            return False
    
    def delete_comment(self, comment_id: int, performer: str, reason: Optional[str] = None) -> bool:
        """
        Удаление комментария.
        
        Args:
            comment_id: ID комментария для удаления
            performer: Имя пользователя, выполняющего удаление
            reason: Причина удаления
            
        Returns:
            True если удаление успешно
            
        Raises:
            ValueError: Если комментарий не найден
        """
        # Получаем текущий комментарий
        comment = self._get_comment(comment_id)
        if not comment:
            raise ValueError(f"Комментарий с ID {comment_id} не найден")
        
        previous_status = CommentStatus(comment['status'])
        
        # Обновляем статус
        success = self._update_comment_status(
            comment_id, 
            CommentStatus.DELETED, 
            reason
        )
        
        if success:
            # Логируем действие
            self._log_moderation_action(
                comment_id=comment_id,
                action=CommentAction.DELETE,
                performer=performer,
                reason=reason,
                previous_status=previous_status,
                new_status=CommentStatus.DELETED
            )
            
            logger.warning(f"Comment {comment_id} deleted by {performer}. Reason: {reason}")
        
        return success
    
    def hide_comment(self, comment_id: int, performer: str, reason: Optional[str] = None) -> bool:
        """
        Скрытие комментария.
        
        Args:
            comment_id: ID комментария для скрытия
            performer: Имя пользователя, выполняющего скрытие
            reason: Причина скрытия
            
        Returns:
            True если скрытие успешно
            
        Raises:
            ValueError: Если комментарий не найден
        """
        # Получаем текущий комментарий
        comment = self._get_comment(comment_id)
        if not comment:
            raise ValueError(f"Комментарий с ID {comment_id} не найден")
        
        previous_status = CommentStatus(comment['status'])
        
        # Проверяем, не удален ли уже комментарий
        if previous_status == CommentStatus.DELETED:
            raise ValueError("Нельзя скрыть удаленный комментарий")
        
        # Обновляем статус
        success = self._update_comment_status(
            comment_id, 
            CommentStatus.HIDDEN, 
            reason
        )
        
        if success:
            # Логируем действие
            self._log_moderation_action(
                comment_id=comment_id,
                action=CommentAction.HIDE,
                performer=performer,
                reason=reason,
                previous_status=previous_status,
                new_status=CommentStatus.HIDDEN
            )
            
            logger.info(f"Comment {comment_id} hidden by {performer}. Reason: {reason}")
        
        return success
    
    def restore_comment(self, comment_id: int, performer: str) -> bool:
        """
        Восстановление комментария.
        
        Args:
            comment_id: ID комментария для восстановления
            performer: Имя пользователя, выполняющего восстановление
            
        Returns:
            True если восстановление успешно
        """
        comment = self._get_comment(comment_id)
        if not comment:
            raise ValueError(f"Комментарий с ID {comment_id} не найден")
        
        previous_status = CommentStatus(comment['status'])
        
        # Только скрытые или удаленные комментарии можно восстановить
        if previous_status not in [CommentStatus.HIDDEN, CommentStatus.DELETED]:
            raise ValueError(f"Комментарий в статусе {previous_status} нельзя восстановить")
        
        # Восстанавливаем в published
        success = self._update_comment_status(comment_id, CommentStatus.PUBLISHED, None)
        
        if success:
            self._log_moderation_action(
                comment_id=comment_id,
                action=CommentAction.RESTORE,
                performer=performer,
                reason=None,
                previous_status=previous_status,
                new_status=CommentStatus.PUBLISHED
            )
            
            logger.info(f"Comment {comment_id} restored by {performer}")
        
        return success

# --- API Models ---
class ModerationRequest(BaseModel):
    """Модель запроса на модерацию."""
    action: CommentAction
    reason: Optional[str] = Field(None, max_length=500)

class ModerationResponse(BaseModel):
    """Модель ответа на модерацию."""
    success: bool
    message: str
    comment_id: int
    action: CommentAction
    new_status: CommentStatus

# --- Инициализация сервисов ---
db_manager = DatabaseManager()
comment_actions = CommentActions(db_manager)

# Добавление тестовых данных
@app.on_event("startup")
async def add_test_data():
    """Добавление тестовых комментариев."""
    try:
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем, есть ли уже тестовые данные
            cursor.execute("SELECT COUNT(*) FROM comments")
            if cursor.fetchone()[0] == 0:
                # Добавляем тестовые комментарии
                test_comments = [
                    ("Отличная статья, спасибо!", 101, "user1", 1, "published"),
                    ("Совершенно не согласен с автором", 102, "user2", 1, "published"),
                    ("Спам-сообщение, купите мои таблетки!", 103, "spammer", 1, "published"),
                    ("Оскорбительный комментарий", 104, "troll", 1, "published"),
                ]
                
                cursor.executemany("""
                    INSERT INTO comments (content, author_id, author_name, post_id, status)
                    VALUES (?, ?, ?, ?, ?)
                """, test_comments)
                
                conn.commit()
                logger.info("Test comments added to database")
                
    except Exception as e:
        logger.error(f"Failed to add test data: {e}")

# --- API Endpoints ---
@app.post("/moderate/{comment_id}", response_model=ModerationResponse)
async def moderate_comment(
    comment_id: int,
    request: ModerationRequest,
    current_user: CurrentUser = Depends(get_current_user)
) -> ModerationResponse:
    """
    Эндпоинт для модерации комментариев.
    
    Args:
        comment_id: ID комментария для модерации
        request: Запрос с действием и причиной
        current_user: Текущий пользователь
        
    Returns:
        Результат модерации
        
    Raises:
        HTTPException: При ошибках доступа или валидации
    """
    # ПРОВЕРКА ПОЛНОМОЧИЙ ПОЛЬЗОВАТЕЛЯ В КОДЕ МЕТОДА
    if not current_user.has_moderation_permission():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для модерации"
        )
    
    try:
        success = False
        new_status = None
        
        # Выполняем действие в зависимости от запроса
        if request.action == CommentAction.DELETE:
            success = comment_actions.delete_comment(
                comment_id, 
                current_user.username, 
                request.reason
            )
            new_status = CommentStatus.DELETED
            
        elif request.action == CommentAction.HIDE:
            success = comment_actions.hide_comment(
                comment_id, 
                current_user.username, 
                request.reason
            )
            new_status = CommentStatus.HIDDEN
            
        elif request.action == CommentAction.RESTORE:
            success = comment_actions.restore_comment(
                comment_id, 
                current_user.username
            )
            new_status = CommentStatus.PUBLISHED
        
        if success:
            return ModerationResponse(
                success=True,
                message=f"Комментарий {comment_id} успешно обработан",
                comment_id=comment_id,
                action=request.action,
                new_status=new_status
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Не удалось выполнить действие {request.action} для комментария {comment_id}"
            )
            
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "не найден" in str(e) else status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error during moderation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера"
        )

@app.get("/logs/{comment_id}", response_model=List[ModerationLog])
async def get_moderation_logs(
    comment_id: int,
    current_user: CurrentUser = Depends(get_current_user)
) -> List[ModerationLog]:
    """
    Получение логов модерации для комментария.
    Доступно только модераторам и администраторам.
    """
    if not current_user.has_moderation_permission():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для просмотра логов"
        )
    
    try:
        with db_manager._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM moderation_logs 
                WHERE comment_id = ? 
                ORDER BY performed_at DESC
            """, (comment_id,))
            
            logs = []
            for row in cursor.fetchall():
                log_data = dict(row)
                # Преобразуем строки в enum
                if log_data['previous_status']:
                    log_data['previous_status'] = CommentStatus(log_data['previous_status'])
                if log_data['new_status']:
                    log_data['new_status'] = CommentStatus(log_data['new_status'])
                log_data['action'] = CommentAction(log_data['action'])
                
                logs.append(ModerationLog(**log_data))
            
            return logs
            
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при получении логов"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)