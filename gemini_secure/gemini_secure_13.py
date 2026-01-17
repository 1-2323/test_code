import markdown
import bleach
from typing import Final, List, Dict, Any
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict


class CommentRequest(BaseModel):
    """Схема входящего сообщения с валидацией текста."""
    text: str = Field(..., min_length=1, max_length=5000)


class CommentResponse(BaseModel):
    """Схема ответа, содержащая безопасный HTML."""
    id: int
    raw_markdown: str
    html_content: str


class ContentSanitizationService:
    """
    Сервис для безопасного преобразования Markdown в HTML.
    Использует строгую фильтрацию по белому списку тегов.
    """

    # Белый список разрешенных HTML-тегов
    ALLOWED_TAGS: Final[List[str]] = [
        'p', 'b', 'i', 'strong', 'em', 'code', 'pre',
        'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'blockquote'
    ]

    # Белый список разрешенных атрибутов
    ALLOWED_ATTRIBUTES: Final[Dict[str, List[str]]] = {
        'code': ['class'],
        'pre': ['class'],
    }

    def render_and_clean(self, raw_text: str) -> str:
        """
        Преобразует Markdown в HTML и очищает его от опасных элементов.
        
        :param raw_text: Текст в формате Markdown.
        :return: Безопасная HTML-строка.
        """
        # 1. Конвертация Markdown в HTML
        # Используем расширение 'fenced_code' для поддержки блоков кода
        untrusted_html = markdown.markdown(
            raw_text, 
            extensions=['fenced_code', 'nl2br']
        )

        # 2. Очистка (Sanitization) по белому списку
        # bleach удаляет все теги и атрибуты, не входящие в списки
        safe_html = bleach.clean(
            untrusted_html,
            tags=self.ALLOWED_TAGS,
            attributes=self.ALLOWED_ATTRIBUTES,
            strip=True  # Удалять небезопасные теги полностью, а не экранировать их
        )

        return safe_html


# --- API Implementation ---

app = FastAPI(title="Forum Content Management System")
content_service = ContentSanitizationService()

# Имитация БД
comments_db: List[Dict[str, Any]] = []


@app.post("/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(request: CommentRequest):
    """
    Принимает Markdown, сохраняет его и возвращает очищенный HTML.
    """
    try:
        # Генерация безопасного представления
        safe_html = content_service.render_and_clean(request.text)

        # Сохранение в "базу данных"
        new_id = len(comments_db) + 1
        comment_entry = {
            "id": new_id,
            "raw_markdown": request.text,
            "html_content": safe_html
        }
        comments_db.append(comment_entry)

        return comment_entry

    except Exception as e:
        # Логируем ошибку внутри, возвращаем общий текст пользователю
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing content."
        )