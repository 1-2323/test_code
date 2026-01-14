from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re

app = Flask(__name__)

def is_valid_url(url):
    """Проверка валидности URL"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def clean_text(text):
    """Очистка текста от лишних пробелов и переносов"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

def get_page_preview(url):
    """Получение предварительного просмотра страницы"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Удаляем ненужные элементы
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()
        
        # Получаем заголовок
        title = ""
        if soup.title and soup.title.string:
            title = clean_text(soup.title.string)
        
        # Ищем мета-описание
        description = ""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            description = clean_text(meta_desc.get('content'))
        
        # Или берем первый значимый абзац
        if not description:
            paragraphs = soup.find_all(['p', 'article', 'main'])
            for p in paragraphs:
                text = clean_text(p.get_text())
                if len(text) > 50 and len(text) < 500:
                    description = text
                    break
        
        # Если описание слишком длинное, обрезаем
        if len(description) > 300:
            description = description[:297] + "..."
        
        # Получаем favicon
        favicon = ""
        icon_link = soup.find('link', rel=lambda x: x and 'icon' in x.lower())
        if icon_link and icon_link.get('href'):
            favicon = icon_link.get('href')
            if not favicon.startswith(('http://', 'https://')):
                base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                favicon = base_url + (favicon if favicon.startswith('/') else '/' + favicon)
        
        return {
            'title': title,
            'description': description,
            'url': url,
            'favicon': favicon,
            'status': 'success'
        }
        
    except requests.exceptions.Timeout:
        return {
            'status': 'error',
            'message': 'Превышено время ожидания ответа от сервера'
        }
    except requests.exceptions.HTTPError as e:
        return {
            'status': 'error',
            'message': f'HTTP ошибка: {e.response.status_code}'
        }
    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'message': f'Ошибка при запросе: {str(e)}'
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Неизвестная ошибка: {str(e)}'
        }

@app.route('/preview', methods=['POST'])
def preview():
    """Эндпоинт для получения предварительного просмотра ссылки"""
    data = request.get_json()
    
    if not data or 'url' not in data:
        return jsonify({
            'status': 'error',
            'message': 'Необходимо указать URL в теле запроса'
        }), 400
    
    url = data['url'].strip()
    
    if not url:
        return jsonify({
            'status': 'error',
            'message': 'URL не может быть пустым'
        }), 400
    
    if not is_valid_url(url):
        return jsonify({
            'status': 'error',
            'message': 'Некорректный URL'
        }), 400
    
    result = get_page_preview(url)
    
    if result['status'] == 'success':
        return jsonify(result), 200
    else:
        return jsonify(result), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'status': 'error',
        'message': 'Эндпоинт не найден'
    }), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        'status': 'error',
        'message': 'Метод не разрешен'
    }), 405

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)