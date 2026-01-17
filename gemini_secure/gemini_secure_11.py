from typing import List, Optional, Dict, Any, Final
from sqlalchemy import create_engine, Column, Integer, String, select, and_
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel, Field, field_validator, ConfigDict

# --- Конфигурация БД ---
Base = declarative_base()

class User(Base):
    """Модель пользователя в базе данных."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False)
    email = Column(String(255), unique=True)

# --- Схемы валидации (Pydantic) ---

class UserResponse(BaseModel):
    """Схема для возврата данных о пользователе."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: str
    email: str

class SearchCriteria(BaseModel):
    """
    Схема валидации входящих параметров поиска.
    Реализует строгую типизацию и ограничения пагинации.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    role: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_-]+$")
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)  # Жесткий верхний лимит 100

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: Optional[str]) -> Optional[str]:
        """Дополнительная очистка строковых параметров."""
        if v is None:
            return v
        return v.strip().replace("%", "").replace("_", "")

# --- Сервис поискового движка ---

class UserSearchEngine:
    """
    Движок для выполнения динамического поиска пользователей.
    Использует безопасную сборку условий запроса.
    """

    MAX_DB_LIMIT: Final[int] = 100

    def __init__(self, db_url: str = "sqlite:///:memory:"):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def search_users(self, criteria: SearchCriteria) -> Dict[str, Any]:
        """
        Формирует и выполняет динамический запрос к БД.
        
        :param criteria: Объект с валидированными параметрами поиска.
        :return: Словарь с результатами и метаданными пагинации.
        """
        session: Session = self.SessionLocal()
        try:
            # Инициализация базового запроса
            query = select(User)
            filters = []

            # Динамическое добавление условий (параметризовано через ORM)
            if criteria.name:
                # Используем ilike для поиска по части имени
                filters.append(User.name.ilike(f"%{criteria.name}%"))
            
            if criteria.role:
                filters.append(User.role == criteria.role)

            if filters:
                query = query.where(and_(*filters))

            # Применение пагинации
            offset = (criteria.page - 1) * criteria.limit
            query = query.offset(offset).limit(criteria.limit)

            # Выполнение запроса
            result = session.execute(query).scalars().all()
            
            # Преобразование в Pydantic модели для сериализации
            users = [UserResponse.model_validate(u) for u in result]

            return {
                "items": users,
                "pagination": {
                    "current_page": criteria.page,
                    "page_size": len(users),
                    "limit_applied": criteria.limit
                }
            }
        finally:
            session.close()

# --- Пример интеграции с FastAPI эндпоинтом ---

from fastapi import FastAPI, Depends

app = FastAPI()
search_engine = UserSearchEngine()

@app.get("/admin/users/search", response_model=Dict[str, Any])
async def search_users_endpoint(criteria: SearchCriteria = Depends()):
    """
    Эндпоинт для поиска пользователей с автоматической валидацией параметров.
    """
    return search_engine.search_users(criteria)