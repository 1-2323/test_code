import markdown
import bleach
from typing import Dict, Any
from sqlalchemy import Column, Integer, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Инициализация декларативной базы SQLAlchemy
Base = declarative_base()

class Comment(Base):
    """Модель комментария для хранения в базе данных."""
    __tablename__ = 'comments'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_markdown = Column(Text, nullable=False)
    html_content = Column(Text, nullable=False)

class ForumCMS:
    """
    Система управления контентом форума.
    Обеспечивает трансформацию Markdown и защиту от XSS.
    """

    def __init__(self, db_session: Session):
        self.db = db_session
        # Белый список разрешенных HTML-тегов для безопасности
        self._allowed_tags = [
            'p', 'br', 'strong', 'em', 'h1', 'h2', 'h3', 
            'ul', 'ol', 'li', 'code', 'pre', 'blockquote', 'a'
        ]
        self._allowed_attrs = {'a': ['href', 'title']}

    def _render_to_safe_html(self, md_text: str) -> str:
        """
        Приватный метод: конвертирует Markdown в HTML и очищает его.
        """
        # 1. Рендеринг Markdown с поддержкой таблиц и блоков кода
        unsafe_html = markdown.markdown(
            md_text, 
            extensions=['extra', 'nl2br', 'fenced_code']
        )
        
        # 2. Очистка (Sanitization) для предотвращения XSS-атак
        return bleach.clean(
            unsafe_html, 
            tags=self._allowed_tags, 
            attributes=self._allowed_attrs
        )

    def post_comment(self, markdown_text: str) -> Dict[str, Any]:
        """
        Обрабатывает POST-запрос на создание комментария.
        
        Логика работы:
        1. Валидация входных данных.
        2. Генерация очищенного HTML-представления.
        3. Атомарное сохранение в базу данных.
        4. Возврат объекта для отображения на фронтенде.
        """
        if not markdown_text or not markdown_text.strip():
            raise ValueError("Комментарий не может быть пустым.")

        # Получаем безопасный HTML
        rendered_html = self._render_to_safe_html(markdown_text)

        # Создаем запись для БД
        new_comment = Comment(
            raw_markdown=markdown_text,
            html_content=rendered_html
        )

        try:
            self.db.add(new_comment)
            self.db.commit()
            self.db.refresh(new_comment)
            
            return {
                "id": new_comment.id,
                "html": new_comment.html_content,
                "status": "created"
            }
        except Exception as e:
            self.db.rollback()
            raise RuntimeError(f"Ошибка при сохранении комментария: {e}")

# --- Пример использования (Эмуляция эндпоинта) ---

if __name__ == "__main__":
    # Настройка БД в памяти для теста
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        cms_service = ForumCMS(session)
        
        # Входящие данные (Markdown + попытка вставить скрипт)
        incoming_md = """
### Привет, форум!
Это сообщение содержит **жирный текст** и [ссылку](https://python.org).
<script>alert('XSS Attack')</script>
        """
        
        try:
            # Обработка комментария
            result = cms_service.post_comment(incoming_md)
            
            print(f"Успешно сохранено. ID: {result['id']}")
            print("HTML-представление (очищенное):")
            print(result['html'])
        except Exception as err:
            print(f"Произошла ошибка: {err}")