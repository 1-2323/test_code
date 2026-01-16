"""
Сервис для получения превью ссылок с извлечением метаданных веб-страниц.
"""

import re
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, HttpUrl, validator
from fastapi import FastAPI, HTTPException, Query, status


# ==================== МОДЕЛИ ДАННЫХ ====================

class LinkMetadata(BaseModel):
    """Модель метаданных страницы."""
    url: HttpUrl = Field(..., description="Исходный URL")
    title: Optional[str] = Field(None, description="Заголовок страницы (тег <title>)")
    description: Optional[str] = Field(None, description="Мета-описание страницы")
    image: Optional[str] = Field(None, description="URL основного изображения (og:image)")
    site_name: Optional[str] = Field(None, description="Название сайта (og:site_name)")
    content_type: Optional[str] = Field(None, description="Content-Type заголовок")
    content_length: Optional[int] = Field(None, description="Размер контента в байтах")
    fetched_at: datetime = Field(default_factory=datetime.now, description="Время получения")
    
    class Config:
        """Конфигурация Pydantic модели."""
        schema_extra = {
            "example": {
                "url": "https://example.com",
                "title": "Example Domain",
                "description": "This domain is for use in illustrative examples in documents.",
                "image": "https://example.com/image.jpg",
                "site_name": "Example",
                "content_type": "text/html; charset=UTF-8",
                "content_length": 1256,
                "fetched_at": "2024-01-15T10:30:00"
            }
        }


class LinkPreviewRequest(BaseModel):
    """Модель запроса для получения превью ссылки."""
    url: HttpUrl = Field(..., description="URL для получения превью")
    timeout: Optional[int] = Field(5, ge=1, le=30, description="Таймаут запроса в секундах")
    follow_redirects: Optional[bool] = Field(True, description="Следовать ли редиректам")
    
    @validator('url')
    def validate_url_scheme(cls, v):
        """Проверяет, что URL использует HTTP или HTTPS."""
        parsed = urlparse(str(v))
        if parsed.scheme not in ('http', 'https'):
            raise ValueError('URL должен использовать протокол HTTP или HTTPS')
        return v


class LinkPreviewResponse(BaseModel):
    """Модель ответа с превью ссылки."""
    success: bool = Field(..., description="Успешно ли получены метаданные")
    metadata: Optional[LinkMetadata] = Field(None, description="Метаданные страницы")
    error: Optional[str] = Field(None, description="Сообщение об ошибке (если есть)")
    processing_time: float = Field(..., description="Время обработки запроса в секундах")
    
    class Config:
        """Конфигурация Pydantic модели."""
        schema_extra = {
            "example": {
                "success": True,
                "metadata": {
                    "url": "https://example.com",
                    "title": "Example Domain",
                    "description": "Example description",
                    "fetched_at": "2024-01-15T10:30:00"
                },
                "error": None,
                "processing_time": 0.85
            }
        }


# ==================== ИСКЛЮЧЕНИЯ ====================

class LinkPreviewError(Exception):
    """Базовое исключение для ошибок получения превью ссылки."""
    pass


class URLValidationError(LinkPreviewError):
    """Исключение для ошибок валидации URL."""
    pass


class NetworkError(LinkPreviewError):
    """Исключение для сетевых ошибок."""
    pass


class TimeoutError(LinkPreviewError):
    """Исключение для таймаутов запроса."""
    pass


class ContentError(LinkPreviewError):
    """Исключение для ошибок обработки контента."""
    pass


# ==================== КЛАСС ДЛЯ ИЗВЛЕЧЕНИЯ МЕТАДАННЫХ ====================

class MetadataExtractor:
    """Класс для извлечения метаданных из HTML страницы."""
    
    @staticmethod
    def extract_from_html(html_content: str, url: str) -> Dict[str, Any]:
        """
        Извлекает метаданные из HTML контента.
        
        Args:
            html_content: HTML код страницы.
            url: Исходный URL для разрешения относительных путей.
            
        Returns:
            Словарь с извлеченными метаданными.
        """
        metadata = {
            'url': url,
            'title': None,
            'description': None,
            'image': None,
            'site_name': None
        }
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Извлекаем заголовок
            title_tag = soup.find('title')
            if title_tag:
                metadata['title'] = title_tag.get_text(strip=True)
            
            # Извлекаем мета-описание
            meta_description = soup.find('meta', attrs={'name': 'description'})
            if meta_description and meta_description.get('content'):
                metadata['description'] = meta_description['content']
            
            # Извлекаем Open Graph метаданные
            og_title = soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                metadata['title'] = og_title['content']
            
            og_description = soup.find('meta', property='og:description')
            if og_description and og_description.get('content'):
                metadata['description'] = og_description['content']
            
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                metadata['image'] = MetadataExtractor._resolve_url(
                    og_image['content'], url
                )
            
            og_site_name = soup.find('meta', property='og:site_name')
            if og_site_name and og_site_name.get('content'):
                metadata['site_name'] = og_site_name['content']
            
            # Если нет Open Graph изображения, ищем первое подходящее изображение
            if not metadata['image']:
                first_image = soup.find('img')
                if first_image and first_image.get('src'):
                    metadata['image'] = MetadataExtractor._resolve_url(
                        first_image['src'], url
                    )
            
            # Чистка и валидация извлеченных данных
            metadata = MetadataExtractor._clean_metadata(metadata)
            
        except Exception as e:
            raise ContentError(f"Ошибка при парсинге HTML: {str(e)}")
        
        return metadata
    
    @staticmethod
    def _resolve_url(relative_url: str, base_url: str) -> str:
        """
        Преобразует относительный URL в абсолютный.
        
        Args:
            relative_url: Относительный URL.
            base_url: Базовый URL для разрешения.
            
        Returns:
            Абсолютный URL.
        """
        if not relative_url:
            return ""
        
        # Если URL уже абсолютный, возвращаем как есть
        if relative_url.startswith(('http://', 'https://', '//')):
            if relative_url.startswith('//'):
                return f"https:{relative_url}"
            return relative_url
        
        # Разбираем базовый URL
        parsed_base = urlparse(base_url)
        
        # Если относительный URL начинается с /, добавляем к домену
        if relative_url.startswith('/'):
            return f"{parsed_base.scheme}://{parsed_base.netloc}{relative_url}"
        
        # Иначе добавляем к пути базового URL
        base_path = parsed_base.path
        if not base_path.endswith('/'):
            base_path = base_path[:base_path.rfind('/') + 1]
        
        return f"{parsed_base.scheme}://{parsed_base.netloc}{base_path}{relative_url}"
    
    @staticmethod
    def _clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Очищает и валидирует извлеченные метаданные.
        
        Args:
            metadata: Словарь с метаданными.
            
        Returns:
            Очищенный словарь с метаданными.
        """
        cleaned = metadata.copy()
        
        # Ограничиваем длину текстовых полей
        max_lengths = {
            'title': 200,
            'description': 500,
            'site_name': 100
        }
        
        for field, max_len in max_lengths.items