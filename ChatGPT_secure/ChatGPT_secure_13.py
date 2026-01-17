from typing import List

import markdown
import bleach
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ConfigDict


# =========================
# НАСТРОЙКИ ОЧИСТКИ HTML
# =========================

ALLOWED_TAGS: List[str] = [
    "p",
    "strong",
    "em",
    "ul",
    "ol",
    "li",
    "a",
    "code",
    "pre",
    "blockquote",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


# =========================
# Pydantic СХЕМЫ
# =========================

class CommentCreateRequest(BaseModel):
    """
    Входные данные для создания комментария.
    """
    text: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class CommentResponse(BaseModel):
    """
    Ответ с HTML-представлением комментария.
    """
    html: str


# =========================
# ХРАНИЛИЩЕ КОММЕНТАРИЕВ
# =========================

class CommentRepository:
    """
    Простейшее in-memory хранилище комментариев.
    """

    def __init__(self) -> None:
        self._storage: List[str] = []

    def save(self, html: str) -> None:
        self._storage.append(html)


# =========================
# СЕРВИС КОНТЕНТА
# =========================

class CommentService:
    """
    Сервис обработки и хранения комментариев форума.
    """

    def __init__(self, repository: CommentRepository) -> None:
        self._repository = repository

    def create_comment(self, markdown_text: str) -> str:
        """
        Преобразует Markdown в HTML, очищает его
        и сохраняет результат.
        """
        raw_html: str = markdown.markdown(
            markdown_text,
            extensions=["fenced_code", "codehilite"],
            output_format="html5",
        )

        clean_html: str = bleach.clean(
            raw_html,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )

        self._repository.save(clean_html)
        return clean_html


# =========================
# FASTAPI ПРИЛОЖЕНИЕ
# =========================

app = FastAPI(
    title="Forum Content Management",
    version="1.0.0",
    description="CMS для комментариев форума",
)

comment_repository = CommentRepository()
comment_service = CommentService(comment_repository)


# =========================
# ENDPOINT
# =========================

@app.post(
    "/comments",
    response_model=CommentResponse,
)
def create_comment(request: CommentCreateRequest) -> CommentResponse:
    """
    Создаёт комментарий из Markdown и возвращает
    безопасное HTML-представление.
    """
    html = comment_service.create_comment(request.text)
    return CommentResponse(html=html)
