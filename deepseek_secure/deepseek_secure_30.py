from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import asyncio
import aiohttp
import psutil
from enum import Enum

class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

@dataclass
class HealthCheckResult:
    """Результат проверки здоровья."""
    service: str
    status: HealthStatus
    response_time: float
    error: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class HealthChecker:
    """Проверка здоровья сервисов."""
    
    def __init__(self):
        self.checks: List[Callable] = []
    
    def add_check(self, check_func: Callable):
        """Добавление проверки."""
        self.checks.append(check_func)
    
    async def check_all(self) -> List[HealthCheckResult]:
        """Выполнение всех проверок."""
        results = []
        
        for check in self.checks:
            try:
                start_time = asyncio.get_event_loop().time()
                await check()
                response_time = asyncio.get_event_loop().time() - start_time
                
                results.append(HealthCheckResult(
                    service=check.__name__,
                    status=HealthStatus.HEALTHY,
                    response_time=response_time
                ))
            except Exception as e:
                results.append(HealthCheckResult(
                    service=check.__name__,
                    status=HealthStatus.UNHEALTHY,
                    response_time=0,
                    error=str(e)
                ))
        
        return results
    
    async def get_system_health(self) -> Dict[str, Any]:
        """Проверка здоровья системы."""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            'cpu_usage': cpu_percent,
            'memory_usage': memory.percent,
            'disk_usage': disk.percent,
            'timestamp': datetime.now().isoformat()
        }

class ServiceHealthMonitor:
    """Мониторинг здоровья сервисов."""
    
    def __init__(self):
        self.health_checker = HealthChecker()
        self._setup_default_checks()
    
    def _setup_default_checks(self):
        """Настройка стандартных проверок."""
        
        @self.health_checker.add_check
        async def check_database():
            """Проверка базы данных."""
            # В реальной системе здесь будет проверка подключения к БД
            await asyncio.sleep(0.1)
        
        @self.health_checker.add_check
        async def check_redis():
            """Проверка Redis."""
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get('http://localhost:6379/health', timeout=2):
                        pass
            except:
                raise ConnectionError("Redis unavailable")
        
        @self.health_checker.add_check
        async def check_external_api():
            """Проверка внешнего API."""
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get('https://api.example.com/health', timeout=5):
                        pass
            except:
                raise ConnectionError("External API unavailable")
    
    async def get_health_report(self) -> Dict[str, Any]:
        """Получение полного отчета о здоровье."""
        system_health = await self.health_checker.get_system_health()
        service_checks = await self.health_checker.check_all()
        
        # Определяем общий статус
        all_healthy = all(check.status == HealthStatus.HEALTHY 
                         for check in service_checks)
        
        overall_status = HealthStatus.HEALTHY if all_healthy else HealthStatus.DEGRADED
        
        return {
            'status': overall_status,
            'timestamp': datetime.now().isoformat(),
            'system': system_health,
            'services': [{
                'name': check.service,
                'status': check.status,
                'response_time_ms': round(check.response_time * 1000, 2),
                'error': check.error
            } for check in service_checks]
        }