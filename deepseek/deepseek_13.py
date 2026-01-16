import markdown
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import html

app = FastAPI()

# Модель для хранения комментариев (в памяти для примера)
comments_db = []

# Модели данных
class CommentCreate(BaseModel):
    text_markdown: str
    author: Optional[str] = "Anonymous"

class CommentResponse(BaseModel):
    id: int
    author: str
    html_content: str
    created_at: datetime

def convert_markdown_to_html(markdown_text: str) -> str:
    """
    Конвертирует Markdown в безопасный HTML.
    
    Args:
        markdown_text: Исходный текст в формате Markdown
        
    Returns:
        Безопасный HTML код
        
    Note:
        Использует расширения для обработки таблиц, код блоков и ссылок
    """
    # Экранирование HTML тегов для безопасности
    escaped_text = html.escape(markdown_text)
    
    # Конвертация Markdown в HTML
    html_content = markdown.markdown(
        escaped_text,
        extensions=[
            'extra',  # Таблицы, аббревиатуры
            'codehilite',  # Подсветка кода
            'nl2br',  # Автоматические переносы строк
            'sane_lists'  # Улучшенные списки
        ]
    )
    
    return html_content

@app.post("/comments", response_model=CommentResponse)
def create_comment(comment: CommentCreate):
    """
    Создает новый комментарий, конвертирует Markdown в HTML и сохраняет.
    
    Args:
        comment: Объект комментария с Markdown текстом
        
    Returns:
        Созданный комментарий с HTML представлением
    """
    # Генерация HTML из Markdown
    html_content = convert_markdown_to_html(comment.text_markdown)
    
    # Создание объекта комментария
    comment_obj = {
        "id": len(comments_db) + 1,
        "author": comment.author,
        "html_content": html_content,
        "created_at": datetime.now()
    }
    
    # Сохранение в БД (в памяти)
    comments_db.append(comment_obj)
    
    return comment_obj