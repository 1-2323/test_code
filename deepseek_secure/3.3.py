from flask import Flask, request, render_template_string, abort, jsonify
import html

app = Flask(__name__)

# Шаблон с экранированием через |e и явным escape в Python
COMMENT_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Комментарий</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 40px auto; }
        .comment { border: 1px solid #ddd; padding: 20px; border-radius: 8px; }
        .meta { color: #666; font-size: 0.9em; margin-bottom: 10px; }
        .content { line-height: 1.5; }
    </style>
</head>
<body>
    <h1>Ваш комментарий</h1>
    <div class="comment">
        <div class="meta">
            <!-- Двойное экранирование: через html.escape и |e в шаблоне -->
            ID: {{ comment_id }}<br>
            Длина: {{ text|length }} символов
        </div>
        <div class="content">
            {{ text|e }}
        </div>
    </div>
</body>
</html>
'''

@app.route('/comments', methods=['POST'])
def create_comment():
    # Проверяем Content-Type
    if not request.is_json:
        abort(400, description="Content-Type должен быть application/json")
    
    data = request.get_json()
    
    # Валидация входных данных
    if not data or 'text' not in data:
        abort(400, description="Требуется поле 'text' в JSON теле")
    
    text = data['text']
    
    if not isinstance(text, str):
        abort(400, description="Поле 'text' должно быть строкой")
    
    if len(text.strip()) == 0:
        abort(400, description="Текст комментария не может быть пустым")
    
    if len(text) > 5000:
        abort(400, description="Комментарий слишком длинный (макс. 5000 символов)")
    
    # Основное экранирование для предотвращения XSS
    escaped_text = html.escape(text)
    
    # Генерация ID (в реальном приложении сохраняли бы в БД)
    import uuid
    comment_id = str(uuid.uuid4())[:8]
    
    # Рендеринг шаблона с уже экранированным текстом
    # Дополнительное экранирование через |e в шаблоне
    return render_template_string(
        COMMENT_TEMPLATE,
        text=escaped_text,
        comment_id=comment_id
    )

@app.errorhandler(400)
def bad_request(error):
    return jsonify({
        'error': 'Bad Request',
        'message': error.description
    }), 400

@app.errorhandler(415)
def unsupported_media_type(error):
    return jsonify({
        'error': 'Unsupported Media Type',
        'message': 'Content-Type должен быть application/json'
    }), 415

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)