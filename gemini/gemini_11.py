from typing import List, Optional, Dict, Any
from sqlalchemy import create_engine, Column, Integer, String, select, and_
from sqlalchemy.orm import declarative_base, sessionmaker, Session, Query

# Инициализация базы данных
Base = declarative_base()

class User(Base):
    """Модель пользователя в системе."""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    email = Column(String, unique=True)

class UserSearchEngine:
    """
    Движок для динамического поиска пользователей в админ-панели.
    Реализует фильтрацию и пагинацию на уровне базы данных.
    """

    def __init__(self, db_session: Session):
        self._db = db_session

    def search_users(
        self, 
        name: Optional[str] = None, 
        role: Optional[str] = None, 
        limit: int = 10, 
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Выполняет поиск пользователей по заданным критериям.
        
        Логика работы:
        1. Создание базового объекта запроса.
        2. Динамическое добавление фильтров (если параметры переданы).
        3. Подсчет общего количества записей (для пагинации на фронтенде).
        4. Применение limit/offset и выполнение запроса.
        """
        # 1. Инициализация запроса
        query: Query = self._db.query(User)

        # 2. Динамическое формирование фильтров
        filters = []
        if name:
            # Поиск по вхождению подстроки (case-insensitive)
            filters.append(User.name.ilike(f"%{name}%"))
        
        if role:
            # Точное совпадение роли
            filters.append(User.role == role)

        if filters:
            query = query.filter(and_(*filters))

        # 3. Получение общего числа совпадений до применения лимитов
        total_count = query.count()

        # 4. Применение пагинации и сортировки
        results = (
            query
            .order_by(User.id.asc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        return {
            "metadata": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "count": len(results)
            },
            "users": [
                {"id": u.id, "name": u.name, "role": u.role, "email": u.email} 
                for u in results
            ]
        }

# --- Пример реализации "эндпоинта" и тестирования ---

if __name__ == "__main__":
    # Настройка Mock-базы в памяти
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        # Предварительное наполнение данными
        sample_users = [
            User(name="Admin Alice", role="admin", email="alice@test.com"),
            User(name="Manager Bob", role="manager", email="bob@test.com"),
            User(name="Support Charlie", role="support", email="charlie@test.com"),
            User(name="Admin Dave", role="admin", email="dave@test.com"),
        ]
        session.add_all(sample_users)
        session.commit()

        # Использование поискового движка
        engine = UserSearchEngine(session)

        # Пример запроса: найти всех администраторов с лимитом 1
        search_result = engine.search_users(role="admin", limit=1)

        print(f"Найдено всего: {search_result['metadata']['total']}")
        for user in search_result['users']:
            print(f"ID: {user['id']} | Name: {user['name']} | Role: {user['role']}")

        # Пример поиска по имени
        name_search = engine.search_users(name="Char")
        print(f"\nПоиск по 'Char': {name_search['users'][0]['name'] if name_search['users'] else 'Никого'}")