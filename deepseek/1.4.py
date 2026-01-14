from fastapi import FastAPI, HTTPException, Depends, status
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.sql import func
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid

# Инициализация FastAPI
app = FastAPI(title="Forum API", version="1.0.0")

# Настройка базы данных (SQLite для примера)
DATABASE_URL = "sqlite:///./forum.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Модель пользователя (упрощенная)
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    is_moderator = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Модель комментария
class Comment(Base):
    __tablename__ = "comments"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    content = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id = Column(String, nullable=False)  # ID связанного поста
    parent_comment_id = Column(String, ForeignKey("comments.id"), nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Связи
    author = relationship("User")
    replies = relationship("Comment", back_populates="parent")
    parent = relationship("Comment", remote_side=[id], back_populates="replies")

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Pydantic модели
class CommentResponse(BaseModel):
    id: str
    content: str
    user_id: int
    post_id: str
    parent_comment_id: Optional[str] = None
    is_deleted: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        orm_mode = True

class DeleteCommentResponse(BaseModel):
    message: str
    comment_id: str
    deleted_at: datetime

# Зависимость для получения сессии БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Зависимость для аутентификации (упрощенная)
def get_current_user(db: Session = Depends(get_db)):
    # В реальном приложении здесь должна быть полноценная аутентификация
    # Для примера возвращаем тестового пользователя-модератора
    user = db.query(User).filter(User.username == "moderator_user").first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

# Проверка прав модератора
def verify_moderator(user: User = Depends(get_current_user)):
    if not user.is_moderator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    return user

# Эндпоинт для удаления комментария
@app.delete(
    "/comments/{comment_id}",
    response_model=DeleteCommentResponse,
    status_code=status.HTTP_200_OK,
    summary="Удалить комментарий",
    description="Удаляет комментарий по ID. Доступно только модераторам."
)
async def delete_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    moderator: User = Depends(verify_moderator)
):
    """
    Удаление комментария по ID.
    
    - **comment_id**: UUID комментария
    - Возвращает подтверждение удаления
    """
    
    # Поиск комментария в базе данных
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    
    # Проверка существования комментария
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Comment with ID {comment_id} not found"
        )
    
    # Проверка, не удален ли уже комментарий
    if comment.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Comment with ID {comment_id} is already deleted"
        )
    
    # Мягкое удаление комментария (soft delete)
    try:
        comment.is_deleted = True
        comment.deleted_at = datetime.utcnow()
        
        # Удаление содержимого (в соответствии с GDPR и политикой приватности)
        comment.content = "[Комментарий удален модератором]"
        
        db.commit()
        db.refresh(comment)
        
        # Возвращаем ответ об успешном удалении
        return DeleteCommentResponse(
            message="Comment successfully deleted",
            comment_id=comment.id,
            deleted_at=comment.deleted_at
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting comment: {str(e)}"
        )

# Дополнительные эндпоинты для полноты контекста
@app.get("/comments/{comment_id}", response_model=CommentResponse)
async def get_comment(
    comment_id: str,
    db: Session = Depends(get_db)
):
    """
    Получить информацию о комментарии по ID.
    """
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found"
        )
    return comment

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)