import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, constr
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    create_engine,
    select,
    delete,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker
from passlib.context import CryptContext

# =========================
# CONFIGURATION
# =========================

DATABASE_URL = "sqlite:///./app.db"
RESET_TOKEN_TTL_MINUTES = 15

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()

# =========================
# DATABASE MODELS
# =========================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)


Base.metadata.create_all(engine)

# =========================
# SCHEMAS
# =========================

class PasswordResetConfirmRequest(BaseModel):
    token: constr(min_length=32, max_length=256)
    new_password: constr(min_length=10, max_length=128)


# =========================
# TOKEN UTILITIES
# =========================

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_reset_token() -> str:
    return secrets.token_urlsafe(48)


# =========================
# SERVICE
# =========================

class PasswordResetService:
    def confirm_reset(self, *, token: str, new_password: str) -> None:
        token_hash = hash_token(token)

        with SessionLocal() as db:
            try:
                db.begin()

                stmt = select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == token_hash
                )
                reset_token: Optional[PasswordResetToken] = db.execute(stmt).scalar_one_or_none()

                if not reset_token:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Неверный или истекший токен",
                    )

                if reset_token.expires_at < datetime.utcnow():
                    db.execute(
                        delete(PasswordResetToken).where(
                            PasswordResetToken.id == reset_token.id
                        )
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Неверный или истекший токен",
                    )

                user = db.get(User, reset_token.user_id)
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Неверный или истекший токен",
                    )

                user.password_hash = pwd_context.hash(new_password)

                db.execute(
                    delete(PasswordResetToken).where(
                        PasswordResetToken.id == reset_token.id
                    )
                )

                db.commit()

            except HTTPException:
                db.rollback()
                raise
            except SQLAlchemyError:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Ошибка обработки запроса",
                )


# =========================
# FASTAPI APPLICATION
# =========================

app = FastAPI(title="Password Reset Service")

password_reset_service = PasswordResetService()


@app.post("/auth/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_reset(payload: PasswordResetConfirmRequest) -> None:
    password_reset_service.confirm_reset(
        token=payload.token,
        new_password=payload.new_password,
    )
