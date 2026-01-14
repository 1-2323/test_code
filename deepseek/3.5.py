import logging
import time
from datetime import datetime
from typing import Callable, Dict, Any
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import json
import hashlib
import ipaddress

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для логирования заголовков и информации о запросах
    """
    
    def __init__(
        self,
        app: ASGIApp,
        log_file: str = "request_logs.json",
        max_body_size: int = 1024 * 10,  # 10KB
        sensitive_headers: set = None,
        log_level: str = "INFO",
        exclude_paths: set = None
    ):
        super().__init__(app)
        self.log_file = log_file
        self.max_body_size = max_body_size
        self.sensitive_headers = sensitive_headers or {
            'authorization',
            'cookie',
            'proxy-authorization',
            'x-api-key',
            'x-access-token',
            'x-csrf-token',
            'set-cookie'
        }
        self.exclude_paths = exclude_paths or {
            '/health',
            '/favicon.ico',
            '/robots.txt'
        }
        
        # Настройка логгера
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Создаем обработчик для записи в файл
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(getattr(logging, log_level.upper()))
        
        # Форматирование логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        
        # Также можно добавить вывод в консоль
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Обработка каждого запроса
        """
        # Пропускаем исключенные пути
        if request.url.path in self.exclude_paths:
            return await call_next(request)
        
        # Засекаем время выполнения
        start_time = time.time()
        
        # Собираем информацию о запросе
        request_info = self._collect_request_info(request)
        
        try:
            # Читаем тело запроса для логирования (если нужно)
            request_body = await self._read_request_body(request)
            request_info["request_body_preview"] = request_body
            
            # Выполняем запрос
            response = await call_next(request)
            
            # Засекаем время выполнения
            process_time = time.time() - start_time
            request_info["process_time_ms"] = round(process_time * 1000, 2)
            
            # Добавляем информацию о ответе
            request_info.update({
                "response_status_code": response.status_code,
                "response_headers": dict(response.headers),
                "response_body_preview": await self._read_response_body(response)
            })
            
            # Логируем успешный запрос
            self._log_request(request_info, level="INFO")
            
            return response
            
        except Exception as e:
            # В случае ошибки
            process_time = time.time() - start_time
            request_info["process_time_ms"] = round(process_time * 1000, 2)
            request_info["error"] = str(e)
            request_info["error_type"] = type(e).__name__
            
            # Логируем ошибку
            self._log_request(request_info, level="ERROR")
            
            raise

    def _collect_request_info(self, request: Request) -> Dict[str, Any]:
        """
        Сбор информации из запроса
        """
        # Базовые данные запроса
        request_info = {
            "request_id": hashlib.md5(f"{time.time()}{request.url}".encode()).hexdigest()[:12],
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_ip": self._get_client_ip(request),
            "user_agent": request.headers.get("user-agent", "Unknown"),
            "headers": self._filter_sensitive_headers(dict(request.headers)),
            "referer": request.headers.get("referer"),
            "accept_language": request.headers.get("accept-language"),
            "accept_encoding": request.headers.get("accept-encoding"),
            "content_type": request.headers.get("content-type"),
            "content_length": request.headers.get("content-length"),
            "host": request.headers.get("host"),
            "scheme": request.url.scheme,
        }
        
        # Определяем тип устройства/браузера
        user_agent = request_info["user_agent"].lower()
        request_info["device_type"] = self._detect_device_type(user_agent)
        request_info["browser"] = self._detect_browser(user_agent)
        request_info["platform"] = self._detect_platform(user_agent)
        
        return request_info

    def _filter_sensitive_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Фильтрация чувствительных заголовков
        """
        filtered_headers = {}
        for key, value in headers.items():
            if key.lower() in self.sensitive_headers:
                filtered_headers[key] = "[FILTERED]"
            else:
                filtered_headers[key] = value
        return filtered_headers

    def _get_client_ip(self, request: Request) -> str:
        """
        Получение реального IP клиента с учетом прокси
        """
        # Проверяем стандартные заголовки прокси
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Берем первый IP из цепочки
            ip = forwarded_for.split(",")[0].strip()
            try:
                # Валидируем IP адрес
                ipaddress.ip_address(ip)
                return ip
            except ValueError:
                pass
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            try:
                ipaddress.ip_address(real_ip)
                return real_ip
            except ValueError:
                pass
        
        # Если заголовков прокси нет, используем client.host
        if hasattr(request, 'client') and request.client:
            return request.client.host
        
        return "unknown"

    async def _read_request_body(self, request: Request) -> str:
        """
        Чтение тела запроса для логирования
        """
        try:
            body = await request.body()
            if len(body) > self.max_body_size:
                return f"[Body too large: {len(body)} bytes, truncated to {self.max_body_size}]"
            
            # Пытаемся декодить как текст
            try:
                body_text = body.decode('utf-8', errors='replace')
                # Если это JSON, форматируем
                if request.headers.get('content-type', '').startswith('application/json'):
                    try:
                        json_body = json.loads(body_text)
                        return json.dumps(json_body, ensure_ascii=False, indent=2)[:self.max_body_size]
                    except:
                        pass
                return body_text[:self.max_body_size]
            except:
                return f"[Binary data: {len(body)} bytes]"
        except Exception:
            return "[Error reading request body]"

    async def _read_response_body(self, response: Response) -> str:
        """
        Чтение тела ответа для логирования
        """
        try:
            # Кэшируем тело ответа
            if not hasattr(response, '_body'):
                return "[Response body not available]"
            
            body = response.body
            if len(body) > self.max_body_size:
                return f"[Response body too large: {len(body)} bytes]"
            
            # Пытаемся декодить как текст
            try:
                body_text = body.decode('utf-8', errors='replace')
                # Если это JSON, форматируем
                if 'application/json' in response.headers.get('content-type', ''):
                    try:
                        json_body = json.loads(body_text)
                        return json.dumps(json_body, ensure_ascii=False, indent=2)[:self.max_body_size]
                    except:
                        pass
                return body_text[:self.max_body_size]
            except:
                return f"[Binary response: {len(body)} bytes]"
        except Exception:
            return "[Error reading response body]"

    def _detect_device_type(self, user_agent: str) -> str:
        """
        Определение типа устройства
        """
        if 'mobile' in user_agent:
            return 'Mobile'
        elif 'tablet' in user_agent:
            return 'Tablet'
        elif 'smart-tv' in user_agent or 'smarttv' in user_agent:
            return 'Smart TV'
        elif 'bot' in user_agent or 'crawler' in user_agent or 'spider' in user_agent:
            return 'Bot/Crawler'
        else:
            return 'Desktop'

    def _detect_browser(self, user_agent: str) -> str:
        """
        Определение браузера
        """
        browsers = {
            'chrome': 'Chrome',
            'firefox': 'Firefox',
            'safari': 'Safari',
            'edge': 'Edge',
            'opera': 'Opera',
            'ie': 'Internet Explorer',
            'vivaldi': 'Vivaldi',
            'brave': 'Brave'
        }
        
        for key, name in browsers.items():
            if key in user_agent:
                return name
        
        return 'Unknown'

    def _detect_platform(self, user_agent: str) -> str:
        """
        Определение платформы/ОС
        """
        platforms = {
            'windows': 'Windows',
            'linux': 'Linux',
            'mac os': 'macOS',
            'android': 'Android',
            'ios': 'iOS',
            'iphone': 'iOS',
            'ipad': 'iOS'
        }
        
        for key, name in platforms.items():
            if key in user_agent:
                return name
        
        return 'Unknown'

    def _log_request(self, request_info: Dict[str, Any], level: str = "INFO"):
        """
        Запись лога в файл
        """
        log_entry = {
            "level": level,
            "request_id": request_info["request_id"],
            "timestamp": request_info["timestamp"],
            "method": request_info["method"],
            "path": request_info["path"],
            "status": request_info.get("response_status_code", "N/A"),
            "client_ip": request_info["client_ip"],
            "user_agent": request_info["user_agent"],
            "device_type": request_info["device_type"],
            "browser": request_info["browser"],
            "platform": request_info["platform"],
            "process_time_ms": request_info.get("process_time_ms", 0),
            "referer": request_info["referer"],
            "content_type": request_info["content_type"]
        }
        
        # Добавляем дополнительную информацию в зависимости от уровня
        if level == "ERROR":
            log_entry["error"] = request_info.get("error")
            log_entry["error_type"] = request_info.get("error_type")
        
        # Форматируем сообщение для логгера
        message_parts = [
            f"method={log_entry['method']}",
            f"path={log_entry['path']}",
            f"status={log_entry['status']}",
            f"ip={log_entry['client_ip']}",
            f"ua={log_entry['user_agent'][:50]}...",
            f"time={log_entry['process_time_ms']}ms"
        ]
        
        log_message = " | ".join(message_parts)
        
        # Логируем с соответствующим уровнем
        if level == "ERROR":
            self.logger.error(log_message, extra=log_entry)
        elif level == "WARNING":
            self.logger.warning(log_message, extra=log_entry)
        else:
            self.logger.info(log_message, extra=log_entry)
        
        # Дополнительно записываем полные данные в JSON файл
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                json.dump(request_info, f, ensure_ascii=False, default=str)
                f.write('\n')
        except Exception as e:
            self.logger.error(f"Failed to write to log file: {str(e)}")

# Пример использования в FastAPI приложении
def setup_logging_middleware(app: FastAPI):
    """
    Инициализация middleware для логирования
    """
    middleware = RequestLoggingMiddleware(
        app,
        log_file="logs/requests.json",
        log_level="INFO",
        exclude_paths={'/health', '/metrics', '/favicon.ico'}
    )
    
    # Добавляем middleware в приложение
    app.add_middleware(RequestLoggingMiddleware, **{
        "log_file": "logs/requests.json",
        "log_level": "INFO",
        "exclude_paths": {'/health', '/metrics', '/favicon.ico'}
    })
    
    # Создаем эндпоинт для просмотра логов (опционально)
    @app.get("/admin/logs", include_in_schema=False)
    async def get_logs(limit: int = 100):
        try:
            with open("logs/requests.json", "r", encoding='utf-8') as f:
                lines = f.readlines()[-limit:]
                logs = [json.loads(line) for line in lines if line.strip()]
                return {"logs": logs, "total": len(logs)}
        except FileNotFoundError:
            return {"logs": [], "total": 0}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return app