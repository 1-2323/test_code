from PIL import Image
import hashlib
from pathlib import Path
from typing import Optional, Tuple
import asyncio
from dataclasses import dataclass

@dataclass
class ImageSize:
    """Размер изображения."""
    width: int
    height: int

class ImageCache:
    """Кеш изображений."""
    
    def __init__(self, cache_dir: str = "./image_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get_cache_key(self, image_path: str, size: Optional[ImageSize] = None) -> str:
        """Генерация ключа кеша."""
        key_data = f"{image_path}"
        if size:
            key_data += f"_{size.width}x{size.height}"
        
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get_cached_path(self, cache_key: str) -> Path:
        """Получение пути к кешированному файлу."""
        return self.cache_dir / f"{cache_key}.jpg"
    
    def is_cached(self, cache_key: str) -> bool:
        """Проверка наличия в кеше."""
        return self.get_cached_path(cache_key).exists()
    
    async def get_image(self, image_path: str, 
                       size: Optional[ImageSize] = None) -> Path:
        """Получение изображения (кешированное или оригинальное)."""
        cache_key = self.get_cache_key(image_path, size)
        cached_path = self.get_cached_path(cache_key)
        
        if self.is_cached(cache_key):
            return cached_path
        
        # Загружаем и обрабатываем изображение
        await self._process_image(image_path, cached_path, size)
        
        return cached_path
    
    async def _process_image(self, src_path: str, dst_path: Path,
                           size: Optional[ImageSize] = None):
        """Обработка и кеширование изображения."""
        loop = asyncio.get_event_loop()
        
        def process():
            with Image.open(src_path) as img:
                # Конвертируем в RGB если нужно
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                
                # Изменяем размер если указан
                if size:
                    img.thumbnail((size.width, size.height), Image.Resampling.LANCZOS)
                
                # Сохраняем в кеш
                img.save(dst_path, 'JPEG', quality=85)
        
        await loop.run_in_executor(None, process)
    
    def clear_cache(self, older_than_days: int = 30) -> int:
        """Очистка старого кеша."""
        import time
        cutoff_time = time.time() - (older_than_days * 86400)
        
        deleted = 0
        for file in self.cache_dir.glob("*.jpg"):
            if file.stat().st_mtime < cutoff_time:
                file.unlink()
                deleted += 1
        
        return deleted