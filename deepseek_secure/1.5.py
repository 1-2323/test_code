import asyncio
import re
import socket
import ipaddress
from urllib.parse import urlparse
from typing import Dict, Optional, Tuple
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, HttpUrl, field_validator
import httpx
from bs4 import BeautifulSoup
import aiofiles

app = FastAPI(title="Link Preview Service", version="1.0.0")

# Конфигурация
MAX_CONTENT_SIZE = 2 * 1024 * 1024  # 2MB
REQUEST_TIMEOUT = 10.0  # секунд
USER_AGENT = "Mozilla/5.0 (compatible; LinkPreviewBot/1.0; +http://example.com/bot)"

# Модель запроса
class PreviewRequest(BaseModel):
    url: HttpUrl
    
    @field_validator('url')
    @classmethod
    def validate_url_scheme(cls, v):
        parsed = urlparse(str(v))
        if parsed.scheme not in ['http', 'https']:
            raise ValueError('Only HTTP and HTTPS protocols are allowed')
        return v

# Модель ответа
class PreviewResponse(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    site_name: Optional[str] = None

# Блокируемые сети и домены
BLOCKED_NETWORKS = [
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
]

BLOCKED_DOMAINS = [
    'localhost',
    'metadata.google.internal',
    '169.254.169.254',
    'metadata',
    'metadata.local',
]

# Загрузка дополнительных запрещенных доменов из файла (если есть)
async def load_additional_blocked_domains():
    try:
        async with aiofiles.open('blocked_domains.txt', mode='r') as f:
            content = await f.read()
            return [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        return []

# Проверка на внутренний IP
def is_internal_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in BLOCKED_NETWORKS:
            if ip in network:
                return True
        return False
    except ValueError:
        return True

# Разрешение домена в IP
async def resolve_host(hostname: str) -> Tuple[bool, Optional[str]]:
    try:
        # Сначала пробуем IPv4
        try:
            info = await asyncio.get_event_loop().getaddrinfo(
                hostname, None, family=socket.AF_INET
            )
            if info:
                ip = info[0][4][0]
                return is_internal_ip(ip), ip
        except socket.gaierror:
            pass
        
        # Затем IPv6
        try:
            info = await asyncio.get_event_loop().getaddrinfo(
                hostname, None, family=socket.AF_INET6
            )
            if info:
                ip = info[0][4][0]
                return is_internal_ip(ip), ip
        except socket.gaierror:
            pass
        
        return True, None  # Не можем разрешить - блокируем
        
    except Exception:
        return True, None  # При ошибке блокируем

# Проверка SSRF
async def validate_url_for_ssrf(url: str) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname
    
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL hostname"
        )
    
    # Проверка доменов
    hostname_lower = hostname.lower()
    for blocked in BLOCKED_DOMAINS:
        if blocked in hostname_lower:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access to domain '{hostname}' is blocked"
            )
    
    # Проверка дополнительных доменов
    additional_blocked = await load_additional_blocked_domains()
    for blocked in additional_blocked:
        if blocked in hostname_lower or hostname_lower.endswith(f".{blocked}"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access to domain '{hostname}' is blocked"
            )
    
    # Проверка IP-адресов в URL
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', hostname):
        if is_internal_ip(hostname):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access to IP '{hostname}' is blocked"
            )
    else:
        # Разрешение домена и проверка IP
        is_internal, resolved_ip = await resolve_host(hostname)
        if is_internal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access to '{hostname}' (resolves to {resolved_ip or 'unknown'}) is blocked"
            )
    
    # Проверка портов
    if parsed.port:
        if parsed.port < 1 or parsed.port > 65535:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid port number"
            )
        # Блокировка портов метаданных
        if parsed.port in [80, 443, 8080, 8443]:
            # Разрешенные порты для HTTP/HTTPS
            pass
        elif parsed.port < 1024:
            # Привилегированные порты (кроме разрешенных выше)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access to port {parsed.port} is blocked"
            )

# Извлечение мета-данных
def extract_metadata(html: str, url: str) -> Dict:
    soup = BeautifulSoup(html, 'html.parser')
    
    result = {
        'title': None,
        'description': None,
        'image': None,
        'site_name': None
    }
    
    # Заголовок
    title_tag = soup.find('title')
    if title_tag:
        result['title'] = title_tag.get_text(strip=True)[:200]
    
    # Мета-описание
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if not meta_desc:
        meta_desc = soup.find('meta', attrs={'property': 'og:description'})
    
    if meta_desc and meta_desc.get('content'):
        result['description'] = meta_desc['content'][:300]
    
    # Изображение
    meta_image = soup.find('meta', attrs={'property': 'og:image'})
    if meta_image and meta_image.get('content'):
        image_url = meta_image['content']
        # Преобразование относительных URL в абсолютные
        if image_url.startswith('/'):
            parsed = urlparse(url)
            image_url = f"{parsed.scheme}://{parsed.netloc}{image_url}"
        result['image'] = image_url
    
    # Название сайта
    meta_site = soup.find('meta', attrs={'property': 'og:site_name'})
    if meta_site and meta_site.get('content'):
        result['site_name'] = meta_site['content'][:100]
    
    return result

# Эндпоинт предварительного просмотра
@app.post("/preview", response_model=PreviewResponse, status_code=status.HTTP_200_OK)
async def create_preview(request: PreviewRequest):
    url_str = str(request.url)
    
    # Проверка SSRF
    await validate_url_for_ssrf(url_str)
    
    # Настройка клиента с ограничениями
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=5.0)
    
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'close',
    }
    
    async with httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
        follow_redirects=True,
        max_redirects=5,
        verify=True  # Всегда проверять SSL
    ) as client:
        try:
            # Запрос с ограничением размера
            response = await client.get(
                url_str,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            
            # Проверка content-type
            content_type = response.headers.get('content-type', '')
            if not ('text/html' in content_type or 'application/xhtml+xml' in content_type):
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Unsupported content type. Only HTML pages are allowed."
                )
            
            # Ограничение размера контента
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > MAX_CONTENT_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Content too large. Maximum size is {MAX_CONTENT_SIZE // 1024 // 1024}MB."
                )
            
            # Чтение с проверкой размера
            content = b''
            async for chunk in response.aiter_bytes():
                content += chunk
                if len(content) > MAX_CONTENT_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Content exceeds maximum size limit."
                    )
            
            html = content.decode('utf-8', errors='ignore')
            
            # Извлечение метаданных
            metadata = extract_metadata(html, url_str)
            
            return PreviewResponse(
                url=url_str,
                title=metadata['title'],
                description=metadata['description'],
                image=metadata['image'],
                site_name=metadata['site_name']
            )
            
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Request timeout"
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Upstream error: {e.response.status_code}"
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch URL: {str(e)}"
            )
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unable to decode content as UTF-8"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal server error: {str(e)}"
            )

# Эндпоинт для проверки здоровья
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "link-preview"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)