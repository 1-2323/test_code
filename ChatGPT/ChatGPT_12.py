from typing import List, Optional

from fastapi import FastAPI, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker, Session


# =========================
# Конфигурация БД
# =========================

DATABASE_URL: str = "sqlite:///./users_search.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# =========================
# ORM-модель
# =========================

class User(Base):
    """
    ORM-модель пользователя.
    """
    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True)
    name: str = Column(String, index=True, nullable=False)
    role: str = Column(String, index=True, nullable=False)


# =========================
# Pydantic-модели
# =========================

class UserResponse(BaseModel):
    """
    Модель пользователя для ответа API.
    """
    id: int
    name: str
    role: str

    class Config:
        orm_mode = True


class PaginatedUsersResponse(BaseModel):
    """
    Модель ответа с пагинацией.
    """
    limit: int
    offset: int
    total: int
    items: List[UserResponse]


# =========================
# Репозиторий
# =========================

class UserSearchEngine:
    """
    Поисковый движок пользователей для админ-панели.
    """

    def __init__(self, db: Session) -> None:
        self._db: Session = db

    def search(
        self,
        name: Optional[str],
        role: Optional[str],
        limit: int,
        offset: int,
    ) -> PaginatedUsersResponse:
        """
        Выполняет динамический поиск пользователей.

        Алгоритм:
        1. Формирование базового SQL-запроса
        2. Добавление фильтров (если переданы)
        3. Подсчёт общего количества
        4. Применение limit/offset
        """
        query = select(User)

        if name:
            query = query.where(User.name.ilike(f"%{name}%"))

        if role:
            query = query.where(User.role == role)

        total: int = self._db.execute(
            query.with_only_columns(User.id)
        ).rowcount

        users = (
            self._db.execute(
                query.limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )

        return PaginatedUsersResponse(
            limit=limit,
            offset=offset,
            total=total,
            items=users,
        )


# =========================
# Dependencies
# =========================

def get_db() -> Session:
    """
    Dependency для получения сессии БД.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_search_engine(db: Session = Depends(get_db)) -> UserSearchEngine:
    """
    Dependency для UserSearchEngine.
    """
    return UserSearchEngine(db=db)


# =========================
# FastAPI-приложение
# =========================

app = FastAPI(title="Admin User Search API")


@app.get("/admin/users/search", response_model=PaginatedUsersResponse)
def search_users(
    name: Optional[str] = Query(None, description="Фильтр по имени"),
    role: Optional[str] = Query(None, description="Фильтр по роли"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    engine: UserSearchEngine = Depends(get_search_engine),
) -> PaginatedUsersResponse:
    """
    Эндпоинт поиска пользователей для админ-панели.
    """
    return engine.search(
        name=name,
        role=role,
        limit=limit,
        offset=offset,
    )


# =========================
# Инициализация БД
# =========================

def init_database() -> None:
    """
    Создаёт таблицы и наполняет тестовыми данными.
    """
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    db.add_all(
        [
            User(name="Alice", role="admin"),
            User(name="Bob", role="moderator"),
            User(name="Charlie", role="user"),
            User(name="Alex", role="user"),
        ]
    )
    db.commit()
    db.close()
