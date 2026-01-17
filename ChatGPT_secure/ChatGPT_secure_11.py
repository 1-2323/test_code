from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import (
    Column,
    Integer,
    String,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    Session,
)


# =========================
# SQLALCHEMY BASE
# =========================

Base = declarative_base()


# =========================
# ORM МОДЕЛЬ
# =========================

class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    role = Column(String(50), nullable=False, index=True)


# =========================
# Pydantic СХЕМЫ
# =========================

class UserResponse(BaseModel):
    id: int
    name: str
    role: str


class UserSearchQuery(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    role: Optional[str] = Field(default=None, min_length=1, max_length=50)
    limit: int = Field(default=10, ge=1, le=50)

    model_config = ConfigDict(extra="forbid")


# =========================
# РЕПОЗИТОРИЙ ПОИСКА
# =========================

class UserSearchEngine:
    """
    Поисковый движок пользователей для админ-панели.
    """

    def __init__(self, session: Session) -> None:
        self._session: Session = session

    def search_users(
        self,
        query: UserSearchQuery,
    ) -> List[UserResponse]:
        """
        Выполняет поиск пользователей с динамическими условиями.
        """
        statement = select(UserORM)

        if query.name is not None:
            statement = statement.where(UserORM.name.ilike(f"%{query.name}%"))

        if query.role is not None:
            statement = statement.where(UserORM.role == query.role)

        statement = statement.limit(query.limit)

        result = self._session.execute(statement).scalars().all()

        return [
            UserResponse(
                id=user.id,
                name=user.name,
                role=user.role,
            )
            for user in result
        ]


# =========================
# ИНИЦИАЛИЗАЦИЯ БД
# =========================

DATABASE_URL = "sqlite:///users_search.db"

engine = create_engine(
    DATABASE_URL,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)

Base.metadata.create_all(engine)


def get_db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# =========================
# FASTAPI ПРИЛОЖЕНИЕ
# =========================

app = FastAPI(
    title="User Search Engine",
    version="1.0.0",
)


# =========================
# ENDPOINT
# =========================

@app.get(
    "/admin/users/search",
    response_model=List[UserResponse],
)
def search_users(
    name: Optional[str] = Query(default=None, min_length=1, max_length=100),
    role: Optional[str] = Query(default=None, min_length=1, max_length=50),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_db_session),
) -> List[UserResponse]:
    """
    Эндпоинт поиска пользователей с пагинацией.
    """
    query = UserSearchQuery(
        name=name,
        role=role,
        limit=limit,
    )

    engine = UserSearchEngine(session)
    return engine.search_users(query)
