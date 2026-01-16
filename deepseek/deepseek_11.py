from fastapi import FastAPI, Query, Depends
from sqlalchemy import create_engine, Column, Integer, String, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Optional, List
from pydantic import BaseModel

# Инициализация FastAPI
app = FastAPI()

# Настройка базы данных (SQLite для примера)
DATABASE_URL = "sqlite:///./users.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Модель пользователя в БД
class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    role = Column(String)
    email = Column(String)

Base.metadata.create_all(bind=engine)

# Pydantic модель для ответа
class UserResponse(BaseModel):
    id: int
    name: str
    role: str
    email: str

    class Config:
        orm_mode = True

# Зависимость для получения сессии БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/users/search", response_model=List[UserResponse])
def search_users(
    name: Optional[str] = Query(None, description="Поиск по имени (частичное совпадение)"),
    role: Optional[str] = Query(None, description="Фильтр по роли"),
    limit: int = Query(10, ge=1, le=100, description="Лимит результатов"),
    db: Session = Depends(get_db)
):
    """
    Динамический поиск пользователей с фильтрацией и пагинацией.
    
    Args:
        name: Частичное совпадение имени (ILIKE)
        role: Точное совпадение роли
        limit: Количество возвращаемых записей (пагинация)
        db: Сессия базы данных
    
    Returns:
        Список пользователей, соответствующих критериям
    """
    query = db.query(UserDB)
    
    # Динамическое добавление фильтров
    if name:
        query = query.filter(UserDB.name.ilike(f"%{name}%"))
    if role:
        query = query.filter(UserDB.role == role)
    
    # Применение лимита (пагинация)
    users = query.limit(limit).all()
    
    return users