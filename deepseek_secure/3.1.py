import sqlite3
from typing import Optional, Dict, Any, List, Tuple
from flask import Flask, request, jsonify

app = Flask(__name__)

def search_users(name: Optional[str], role: Optional[str], page: int = 1, limit: int = 10) -> Tuple[List[Dict[str, Any]], int]:
    """
    Поиск пользователей с фильтрацией и пагинацией
    Возвращает кортеж: (список пользователей, общее количество)
    """
    # Подключение к БД (в реальном проекте используйте пул соединений)
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row  # Для доступа к колонкам по имени
    cursor = conn.cursor()
    
    # Базовые части запроса
    base_query = """
        FROM users
        WHERE 1=1
    """
    count_query = "SELECT COUNT(*) " + base_query
    select_query = """
        SELECT id, username, email, role, created_at, is_active
    """ + base_query
    
    # Параметры для фильтрации
    params = []
    
    # Динамическое построение WHERE с защитой от SQL-инъекций
    if name:
        base_query += " AND (username LIKE ? OR email LIKE ?)"
        search_pattern = f"%{name}%"
        params.extend([search_pattern, search_pattern])
    
    if role:
        base_query += " AND role = ?"
        params.append(role)
    
    # Обновляем запросы с учетом фильтров
    count_query = "SELECT COUNT(*) " + base_query.split('FROM')[1]
    select_query = """
        SELECT id, username, email, role, created_at, is_active
    """ + base_query.split('FROM')[1]
    
    # Добавляем сортировку и пагинацию к основному запросу
    select_query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    
    # Выполняем запрос для получения общего количества
    cursor.execute(count_query, params)
    total_users = cursor.fetchone()[0]
    
    # Параметры для пагинации
    pagination_params = params.copy()
    pagination_params.extend([limit, (page - 1) * limit])
    
    # Выполняем основной запрос
    cursor.execute(select_query, pagination_params)
    rows = cursor.fetchall()
    
    # Преобразуем результат в список словарей
    users = []
    for row in rows:
        users.append({
            'id': row['id'],
            'username': row['username'],
            'email': row['email'],
            'role': row['role'],
            'created_at': row['created_at'],
            'is_active': bool(row['is_active'])
        })
    
    conn.close()
    return users, total_users

@app.route('/admin/users/search', methods=['GET'])
def admin_users_search():
    """
    Эндпоинт для поиска пользователей в админ-панели
    Параметры:
        name: строка для поиска по имени пользователя или email (опционально)
        role: роль пользователя (опционально)
        page: номер страницы (по умолчанию 1)
        limit: количество записей на странице (по умолчанию 10, максимум 100)
    """
    try:
        # Получаем и валидируем параметры
        name = request.args.get('name', '').strip() or None
        role = request.args.get('role', '').strip() or None
        
        try:
            page = int(request.args.get('page', 1))
            page = max(1, page)  # Страница не может быть меньше 1
        except ValueError:
            page = 1
            
        try:
            limit = int(request.args.get('limit', 10))
            limit = max(1, min(limit, 100))  # Ограничиваем лимит от 1 до 100
        except ValueError:
            limit = 10
        
        # Выполняем поиск
        users, total = search_users(name, role, page, limit)
        
        # Рассчитываем метаданные пагинации
        total_pages = (total + limit - 1) // limit if limit > 0 else 0
        
        response = {
            'data': users,
            'meta': {
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total_items': total,
                    'total_pages': total_pages,
                    'has_prev': page > 1,
                    'has_next': page < total_pages
                },
                'filters': {
                    'name': name,
                    'role': role
                }
            }
        }
        
        return jsonify(response), 200
        
    except sqlite3.Error as e:
        app.logger.error(f"Database error: {str(e)}")
        return jsonify({
            'error': 'Database error',
            'message': 'Произошла ошибка при выполнении запроса'
        }), 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            'error': 'Internal server error',
            'message': 'Внутренняя ошибка сервера'
        }), 500

if __name__ == '__main__':
    # В продакшене используйте production-ready сервер (Gunicorn, uWSGI)
    app.run(debug=True, host='0.0.0.0', port=5000)