from datetime import date, datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
import uuid

# SQLAlchemy models
Base = declarative_base()

class DBCategory(Base):
    __tablename__ = "categories"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    items = relationship("DBItem", back_populates="category")

class DBItem(Base):
    __tablename__ = "items"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(Integer, nullable=False)  # в копейках/центах
    quantity = Column(Integer, nullable=False, default=0)
    category_id = Column(String(36), ForeignKey("categories.id"), nullable=False)
    manufactured_date = Column(Date, nullable=True)
    
    category = relationship("DBCategory", back_populates="items")

# Pydantic validation models
class CategorySchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Название категории")
    description: Optional[str] = Field(None, max_length=500, description="Описание категории")
    
    @validator('name')
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError('Название категории не может быть пустым')
        return v.strip()

class ItemSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Название товара")
    description: Optional[str] = Field(None, max_length=1000, description="Описание товара")
    price: int = Field(..., gt=0, le=100000000, description="Цена в копейках/центах")
    quantity: int = Field(0, ge=0, le=1000000, description="Количество на складе")
    category_name: str = Field(..., description="Название категории")
    manufactured_date: Optional[date] = Field(None, description="Дата производства")
    
    @validator('name')
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError('Название товара не может быть пустым')
        return v.strip()
    
    @validator('manufactured_date')
    def validate_manufactured_date(cls, v):
        if v and v > date.today():
            raise ValueError('Дата производства не может быть в будущем')
        return v

class ImportRequestSchema(BaseModel):
    categories: Optional[List[CategorySchema]] = Field(
        default_factory=list, 
        description="Список категорий"
    )
    items: Optional[List[ItemSchema]] = Field(
        default_factory=list, 
        description="Список товаров"
    )
    
    @validator('items')
    def validate_items_require_categories(cls, v, values):
        if v and not values.get('categories'):
            raise ValueError('Товары требуют наличия категорий в запросе')
        return v

class ImportResponseSchema(BaseModel):
    message: str
    imported_categories: int
    imported_items: int
    import_id: str
    timestamp: datetime

# FastAPI application
app = FastAPI(
    title="Data Import API",
    description="API для импорта структурированных данных",
    version="1.0.0"
)

# Database setup
DATABASE_URL = "sqlite:///./import_data.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post(
    "/import",
    response_model=ImportResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Импорт категорий и товаров",
    tags=["Импорт данных"]
)
async def import_data(
    import_request: ImportRequestSchema,
    db: Session = Depends(get_db)
):
    """
    Импорт структурированных данных (категории и товары) в базу данных.
    
    - Валидирует входные данные по схеме
    - Создает отсутствующие категории
    - Импортирует товары с привязкой к категориям
    - Возвращает статистику импорта
    """
    try:
        import_id = str(uuid.uuid4())
        
        # Словарь для быстрого поиска категорий по имени
        category_map = {}
        imported_categories_count = 0
        imported_items_count = 0
        
        # Обработка категорий
        if import_request.categories:
            for category_data in import_request.categories:
                # Проверяем существование категории
                existing_category = db.query(DBCategory).filter(
                    DBCategory.name == category_data.name
                ).first()
                
                if not existing_category:
                    # Создаем новую категорию
                    db_category = DBCategory(
                        id=str(uuid.uuid4()),
                        name=category_data.name,
                        description=category_data.description
                    )
                    db.add(db_category)
                    category_map[category_data.name] = db_category
                    imported_categories_count += 1
                else:
                    category_map[category_data.name] = existing_category
        
        # Обработка товаров
        if import_request.items:
            for item_data in import_request.items:
                # Проверяем существование категории для товара
                if item_data.category_name not in category_map:
                    # Если категория не была передана в запросе, ищем в БД
                    existing_category = db.query(DBCategory).filter(
                        DBCategory.name == item_data.category_name
                    ).first()
                    
                    if not existing_category:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Категория '{item_data.category_name}' не найдена и не была предоставлена в запросе"
                        )
                    category_map[item_data.category_name] = existing_category
                
                # Проверяем дубликат товара (по имени и категории)
                existing_item = db.query(DBItem).join(DBCategory).filter(
                    DBItem.name == item_data.name,
                    DBCategory.name == item_data.category_name
                ).first()
                
                if existing_item:
                    # Обновляем существующий товар (опционально, можно изменить логику)
                    existing_item.description = item_data.description or existing_item.description
                    existing_item.price = item_data.price
                    existing_item.quantity = item_data.quantity
                    existing_item.manufactured_date = item_data.manufactured_date
                else:
                    # Создаем новый товар
                    db_item = DBItem(
                        id=str(uuid.uuid4()),
                        name=item_data.name,
                        description=item_data.description,
                        price=item_data.price,
                        quantity=item_data.quantity,
                        category_id=category_map[item_data.category_name].id,
                        manufactured_date=item_data.manufactured_date
                    )
                    db.add(db_item)
                
                imported_items_count += 1
        
        # Фиксируем изменения
        db.commit()
        
        return ImportResponseSchema(
            message="Данные успешно импортированы",
            imported_categories=imported_categories_count,
            imported_items=imported_items_count,
            import_id=import_id,
            timestamp=datetime.now()
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при импорте данных: {str(e)}"
        )

@app.get("/health", tags=["Система"])
async def health_check():
    """Проверка работоспособности API"""
    return {"status": "healthy", "timestamp": datetime.now()}