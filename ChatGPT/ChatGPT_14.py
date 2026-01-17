from datetime import datetime
from typing import Optional

import markdown
from fastapi import FastAPI, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session


# =========================
# Конфигурация БД
# =========================

DATABASE_URL: str = "sqlite:///./forum.db"

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

class Comment(Base):
    """
    ORM-модель комментария форума.
    """
    __tablename__ = "comments"

    id: int = Column(Integer, primary_key=True)
    markdown_text: str = Column(String, nullable=False)
    created_at: datetime = Column(DateTime, default=datetime.utcnow)


# =========================
# Pydantic-модели
# =========================

class CommentCreateRequest(BaseModel):
    """
    Входная модель создания комментария.
    """
    text: str = Field(
