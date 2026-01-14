from fastapi import FastAPI, HTTPException, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

# Инициализация приложения
app = FastAPI(title="Forum API")

# Модели базы данных
Base = declarative_base()

class UserDB(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    is_admin = Column(Boolean, default=False)
    comments = relationship("CommentDB", back_populates="author")

class CommentDB(Base):
    __tablename__ = "comments"
    
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"))
    author_id = Column(Integer, ForeignKey("users.id"))
    author = relationship("UserDB", back_populates="comments")
    post = relationship("PostDB", back_populates="comments")

class PostDB(Base):
    __tablename__ = "posts"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(String, nullable=False)
    comments = relationship("CommentDB", back_populates="post")

# Настройка базы данных (SQLite для примера)
DATABASE_URL = "sqlite:///./forum.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Pydantic схемы
class User(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    
    class Config:
        from_attributes = True

class Comment(BaseModel):
    id: int
    content: str
    post_id: int
    author_id: int
    
    class Config:
        from_attributes = True

# Зависимости
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(db: Session = Depends(get_db)):
    # В реальном приложении здесь должна быть аутентификация через токен
    # Для примера берем первого администратора из базы
    admin_user = db.query(UserDB).filter(UserDB.is_admin == True).first()
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin user not found"
        )
    return admin_user

def check_admin_permissions(user: UserDB = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions. Admin access required."
        )
    return user

# Эндпоинт для удаления комментария
@app.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить комментарий",
    description="Удаление комментария по ID. Доступно только администраторам (is_admin=True)."
)
async def delete_comment(
    comment_id: int,
    current_user: UserDB = Depends(check_admin_permissions),
    db: Session = Depends(get_db)
):
    """
    Удаляет комментарий по указанному ID.
    
    - **comment_id**: ID комментария для удаления
    - **Требуемая роль**: Администратор (is_admin=True)
    
    Возвращает статус 204 No Content при успешном удалении.
    """
    
    # Поиск комментария в базе данных
    comment = db.query(CommentDB).filter(CommentDB.id == comment_id).first()
    
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Comment with ID {comment_id} not found"
        )
    
    try:
        # Удаление комментария
        db.delete(comment)
        db.commit()
        
        # Возвращаем статус 204 без содержимого
        return None
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete comment: {str(e)}"
        )

# Дополнительный эндпоинт для проверки доступности API
@app.get("/health")
async def health_check():
    """Проверка работоспособности API"""
    return {"status": "healthy", "service": "forum-api"}