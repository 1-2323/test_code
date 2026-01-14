from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator
import html
from datetime import datetime
from typing import Optional
import bleach

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Модель для валидации комментария
class CommentCreate(BaseModel):
    text: str
    author_name: Optional[str] = "Аноним"
    parent_id: Optional[int] = None

    @field_validator('text')
    @classmethod
    def validate_text_length(cls, v):
        if len(v.strip()) < 1:
            raise ValueError('Текст комментария не может быть пустым')
        if len(v) > 5000:
            raise ValueError('Текст комментария не может превышать 5000 символов')
        return v.strip()

    @field_validator('author_name')
    @classmethod
    def validate_author_name(cls, v):
        if v is None:
            v = "Аноним"
        v = v.strip()
        if len(v) > 50:
            raise ValueError('Имя автора не может превышать 50 символов')
        return v or "Аноним"

# Хранилище комментариев (временное, для демонстрации)
comments_storage = []
comment_id_counter = 1

def sanitize_html(text: str) -> str:
    """Очистка HTML для предотвращения XSS"""
    # Разрешенные теги для форматирования
    allowed_tags = [
        'p', 'br', 'b', 'i', 'u', 'em', 'strong', 
        'code', 'pre', 'blockquote', 'ul', 'ol', 'li'
    ]
    allowed_attributes = {
        '*': ['style'],
        'a': ['href', 'title', 'rel']
    }
    allowed_styles = ['color', 'font-weight', 'text-decoration']
    
    # Сначала экранируем все
    text = html.escape(text)
    
    # Затем разрешаем безопасные теги (опционально, если хотим разрешить HTML)
    # Для простоты оставляем только экранирование
    return text

def format_comment_text(text: str) -> str:
    """Форматирование текста комментария"""
    # Заменяем переносы строк на <br>
    text = text.replace('\n', '<br>')
    
    # Безопасная обработка ссылок (базовый вариант)
    import re
    # Находим ссылки и оборачиваем их в теги
    url_pattern = re.compile(r'(https?://[^\s<>]+|www\.[^\s<>]+[^\s<>\.])')
    text = url_pattern.sub(r'<a href="\1" target="_blank" rel="nofollow">\1</a>', text)
    
    return text

@router.post("/comments", response_class=HTMLResponse)
async def create_comment(
    request: Request,
    text: str = Form(...),
    author_name: Optional[str] = Form("Аноним"),
    parent_id: Optional[int] = Form(None)
):
    """
    Создание нового комментария и отображение его в шаблоне
    """
    try:
        # Валидация данных
        comment_data = CommentCreate(
            text=text,
            author_name=author_name,
            parent_id=parent_id
        )
        
        # Проверяем существование родительского комментария
        if comment_data.parent_id:
            parent_exists = any(c['id'] == comment_data.parent_id for c in comments_storage)
            if not parent_exists:
                comment_data.parent_id = None
        
        # Генерируем ID комментария
        global comment_id_counter
        comment_id = comment_id_counter
        comment_id_counter += 1
        
        # Подготавливаем данные комментария
        comment = {
            'id': comment_id,
            'text': format_comment_text(comment_data.text),
            'raw_text': comment_data.text,  # Сохраняем оригинальный текст
            'author_name': html.escape(comment_data.author_name),
            'parent_id': comment_data.parent_id,
            'created_at': datetime.now().strftime("%d.%m.%Y %H:%M"),
            'timestamp': datetime.now().isoformat()
        }
        
        # Добавляем комментарий в хранилище
        comments_storage.append(comment)
        
        # Сортируем комментарии по дате (новые сверху)
        sorted_comments = sorted(
            comments_storage, 
            key=lambda x: x['timestamp'], 
            reverse=True
        )
        
        # Рендерим шаблон с комментариями
        return templates.TemplateResponse(
            "comments_list.html",
            {
                "request": request,
                "comments": sorted_comments,
                "new_comment": comment,
                "total_comments": len(comments_storage)
            }
        )
        
    except ValueError as e:
        # В случае ошибки валидации возвращаем форму с ошибкой
        return templates.TemplateResponse(
            "comment_form.html",
            {
                "request": request,
                "error": str(e),
                "prev_text": text,
                "prev_author": author_name
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при создании комментария: {str(e)}"
        )

# Дополнительный эндпоинт для получения формы комментария
@router.get("/comments/form", response_class=HTMLResponse)
async def get_comment_form(request: Request):
    """Получение HTML-формы для комментария"""
    return templates.TemplateResponse(
        "comment_form.html",
        {"request": request}
    )

# Эндпоинт для получения списка комментариев
@router.get("/comments", response_class=HTMLResponse)
async def get_comments(request: Request):
    """Получение всех комментариев"""
    sorted_comments = sorted(
        comments_storage, 
        key=lambda x: x['timestamp'], 
        reverse=True
    )
    
    return templates.TemplateResponse(
        "comments_list.html",
        {
            "request": request,
            "comments": sorted_comments,
            "total_comments": len(comments_storage)
        }
    )