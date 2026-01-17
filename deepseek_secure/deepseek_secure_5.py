import requests
import json
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse, urljoin
import socket
import ipaddress
from datetime import datetime
import re
from dataclasses import dataclass
import time

@dataclass
class LinkPreview:
    """Класс для хранения превью ссылки."""
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    site_name: Optional[str] = None
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    fetch_time: Optional[float] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь."""
        result = {
            "url": self.url,
            "title": self.title,
            "description": self.description,
            "image_url": self.image_url,
            "site_name": self.site_name,
            "content_type": self.content_type,
            "content_length": self.content_length,
            "fetch_time_ms": round(self.fetch_time * 1000, 2) if self.fetch_time else None,
            "timestamp": datetime.now().isoformat()
        }
        
        # Удаляем None значения
        return {k: v for k, v in result.items() if v is not None}

class LinkPreviewer:
    """Сервис для получения превью веб-страниц."""
    
    def __init__(
        self, 
        timeout: float = 5.0,
        max_content_size: int = 1024 * 1024,  # 1 MB
        user_agent: str = "LinkPreviewer/1.0"
    ):
        """
        Инициализация превьювера.
        
        Args:
            timeout: Таймаут запроса в секундах
            max_content_size: Максимальный размер контента в байтах
            user_agent: User-Agent для запросов
        """
        self.timeout = timeout
        self.max_content_size = max_content_size
        self.user_agent = user_agent
        
        # Блокируемые сети и хосты
        self.blocked_networks = [
            ipaddress.ip_network('10.0.0.0/8'),
            ipaddress.ip_network('172.16.0.0/12'),
            ipaddress.ip_network('192.168.0.0/16'),
            ipaddress.ip_network('127.0.0.0/8'),
            ipaddress.ip_network('169.254.0.0/16'),
            ipaddress.ip_network('::1/128'),
            ipaddress.ip_network('fc00::/7')
        ]
        
        # Блокируемые домены
        self.blocked_domains = [
            'localhost',
            'localdomain',
            '127.0.0.1',
            '::1',
            '0.0.0.0'
        ]
        
        # Заголовки для запросов
        self.headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'close',
            'Upgrade-Insecure-Requests': '1'
        }
    
    def _is_url_blocked(self, url: str) -> Tuple[bool, Optional[str]]:
        """
        Проверка URL на доступность (блокировка внутренних адресов).
        
        Args:
            url: URL для проверки
            
        Returns:
            Кортеж (заблокирован, причина)
        """
        try:
            parsed_url = urlparse(url)
            
            # Проверка схемы
            if parsed_url.scheme not in ['http', 'https']:
                return True, f"Неподдерживаемая схема: {parsed_url.scheme}"
            
            # Проверка домена
            domain = parsed_url.hostname
            if not domain:
                return True, "Неверный домен"
            
            # Проверка на блокируемые домены
            if domain.lower() in self.blocked_domains:
                return True, f"Домен {domain} заблокирован"
            
            # Проверка на localhost и локальные адреса
            if domain.lower().endswith('.localhost') or domain.lower().endswith('.local'):
                return True, f"Локальный домен: {domain}"
            
            # Разрешение домена в IP
            try:
                ip = socket.gethostbyname(domain)
                
                # Проверка IP на принадлежность к приватным сетям
                ip_addr = ipaddress.ip_address(ip)
                for network in self.blocked_networks:
                    if ip_addr in network:
                        return True, f"IP {ip} находится в приватной сети {network}"
                
                # Проверка на loopback
                if ip_addr.is_loopback:
                    return True, f"IP {ip} является loopback адресом"
                
                # Проверка на multicast
                if ip_addr.is_multicast:
                    return True, f"IP {ip} является multicast адресом"
                
                # Проверка на link-local
                if ip_addr.is_link_local:
                    return True, f"IP {ip} является link-local адресом"
                    
            except socket.gaierror:
                return True, f"Не удалось разрешить домен: {domain}"
            
            return False, None
            
        except Exception as e:
            return True, f"Ошибка проверки URL: {str(e)}"
    
    def _extract_metadata(self, html: str, base_url: str) -> Dict[str, Optional[str]]:
        """
        Извлечение метаданных из HTML.
        
        Args:
            html: HTML контент
            base_url: Базовый URL для разрешения относительных ссылок
            
        Returns:
            Словарь с метаданными
        """
        metadata = {
            'title': None,
            'description': None,
            'image_url': None,
            'site_name': None
        }
        
        try:
            # Извлечение title
            title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
            if title_match:
                metadata['title'] = title_match.group(1).strip()[:200]
            
            # Извлечение meta-тегов
            meta_pattern = r'<meta[^>]+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']+)["\'][^>]*>'
            
            for match in re.finditer(meta_pattern, html, re.IGNORECASE):
                name = match.group(1).lower()
                content = match.group(2).strip()
                
                # Open Graph и стандартные meta-теги
                if 'og:title' in name and not metadata['title']:
                    metadata['title'] = content[:200]
                elif 'og:description' in name or 'description' in name:
                    if not metadata['description'] or 'og:description' in name:
                        metadata['description'] = content[:300]
                elif 'og:image' in name:
                    if not metadata['image_url']:
                        metadata['image_url'] = self._resolve_url(content, base_url)
                elif 'og:site_name' in name:
                    metadata['site_name'] = content[:100]
                elif 'twitter:title' in name and not metadata['title']:
                    metadata['title'] = content[:200]
                elif 'twitter:description' in name and not metadata['description']:
                    metadata['description'] = content[:300]
                elif 'twitter:image' in name and not metadata['image_url']:
                    metadata['image_url'] = self._resolve_url(content, base_url)
            
            # Если title не нашли в meta-тегах, ищем в h1
            if not metadata['title']:
                h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
                if h1_match:
                    metadata['title'] = h1_match.group(1).strip()[:200]
            
        except Exception as e:
            print(f"Error extracting metadata: {e}")
        
        return metadata
    
    def _resolve_url(self, url: str, base_url: str) -> str:
        """
        Преобразование относительного URL в абсолютный.
        
        Args:
            url: Относительный или абсолютный URL
            base_url: Базовый URL
            
        Returns:
            Абсолютный URL
        """
        try:
            return urljoin(base_url, url)
        except:
            return url
    
    def _safe_get(self, url: str) -> Optional[requests.Response]:
        """
        Безопасное выполнение HTTP-запроса.
        
        Args:
            url: URL для запроса
            
        Returns:
            Response объект или None при ошибке
        """
        try:
            # ЖЕСТКИЕ ЛИМИТЫ НА ВРЕМЯ ОЖИДАНИЯ
            response = requests.get(
                url,
                headers=self.headers,
                timeout=(self.timeout, self.timeout),  # (connect, read)
                stream=True,  # Для контроля размера
                allow_redirects=True,
                max_redirects=5
            )
            
            # Контроль размера загружаемых данных
            content_length = 0
            chunks = []
            
            for chunk in response.iter_content(chunk_size=8192):
                content_length += len(chunk)
                chunks.append(chunk)
                
                # ПРЕРЫВАНИЕ ПРИ ПРЕВЫШЕНИИ ЛИМИТА
                if content_length > self.max_content_size:
                    response.close()
                    raise ValueError(f"Превышен максимальный размер контента: {self.max_content_size} байт")
                
                # Прерываем если получили достаточно данных для анализа
                if content_length > 50000:  # 50KB обычно достаточно для метаданных
                    break
            
            # Собираем контент
            response._content = b''.join(chunks)
            
            return response
            
        except requests.exceptions.Timeout:
            raise ValueError(f"Таймаут запроса ({self.timeout} сек)")
        except requests.exceptions.TooManyRedirects:
            raise ValueError("Слишком много редиректов")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Ошибка запроса: {str(e)}")
        except Exception as e:
            raise ValueError(f"Неожиданная ошибка: {str(e)}")
    
    def get_preview(self, url: str) -> LinkPreview:
        """
        Основной метод получения превью ссылки.
        
        Args:
            url: URL для получения превью
            
        Returns:
            Объект LinkPreview с метаданными
            
        Raises:
            ValueError: При ошибках валидации или запроса
        """
        start_time = time.time()
        preview = LinkPreview(url=url)
        
        try:
            # 1. Валидация и проверка безопасности URL
            is_blocked, reason = self._is_url_blocked(url)
            if is_blocked:
                raise ValueError(f"URL заблокирован: {reason}")
            
            # 2. Выполнение HTTP-запроса
            response = self._safe_get(url)
            if not response:
                raise ValueError("Не удалось получить ответ от сервера")
            
            # 3. Сохранение базовой информации
            preview.content_type = response.headers.get('Content-Type', '').split(';')[0]
            preview.content_length = len(response.content) if response.content else 0
            
            # 4. Проверка типа контента
            if 'text/html' not in preview.content_type.lower():
                # Не HTML контент
                preview.title = f"Файл: {urlparse(url).path.split('/')[-1]}"
                preview.fetch_time = time.time() - start_time
                return preview
            
            # 5. Извлечение метаданных из HTML
            html_content = response.text[:500000]  # Ограничиваем для парсинга
            
            metadata = self._extract_metadata(html_content, url)
            preview.title = metadata['title']
            preview.description = metadata['description']
            preview.image_url = metadata['image_url']
            preview.site_name = metadata['site_name']
            
            # 6. Заполнение дефолтных значений если метаданных нет
            if not preview.title:
                preview.title = urlparse(url).netloc
            
            preview.fetch_time = time.time() - start_time
            return preview
            
        except ValueError as e:
            preview.error = str(e)
            preview.fetch_time = time.time() - start_time
            return preview
        except Exception as e:
            preview.error = f"Неожиданная ошибка: {str(e)}"
            preview.fetch_time = time.time() - start_time
            return preview
    
    def get_preview_json(self, url: str) -> str:
        """
        Получение превью в формате JSON.
        
        Args:
            url: URL для получения превью
            
        Returns:
            JSON строка с метаданными
        """
        preview = self.get_preview(url)
        return json.dumps(preview.to_dict(), ensure_ascii=False, indent=2)

# --- Пример использования ---
def main():
    """Демонстрация работы LinkPreviewer."""
    previewer = LinkPreviewer(timeout=3.0, max_content_size=512 * 1024)
    
    # Тестовые URL (в реальном приложении будут приходить извне)
    test_urls = [
        "https://example.com",
        "https://httpbin.org/html",
        "http://localhost:8080",  # Должен быть заблокирован
        "http://192.168.1.1/admin",  # Должен быть заблокирован
        "https://nonexistent-domain-12345.com",  # Ошибка соединения
    ]
    
    for url in test_urls:
        print(f"\n{'='*60}")
        print(f"Processing: {url}")
        
        preview = previewer.get_preview(url)
        
        if preview.error:
            print(f"Error: {preview.error}")
        else:
            print(f"Title: {preview.title}")
            print(f"Description: {preview.description}")
            print(f"Site: {preview.site_name}")
            print(f"Image: {preview.image_url}")
            print(f"Fetch time: {preview.fetch_time:.2f}s")
        
        # JSON вывод
        # print(previewer.get_preview_json(url))

if __name__ == "__main__":
    main()