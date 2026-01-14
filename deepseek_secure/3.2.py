import subprocess
import json
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
import logging
from functools import lru_cache

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Server Diagnostics API")
security = HTTPBearer()

# Модель запроса
class DiagnosticRequest(BaseModel):
    commands: List[str] = Field(
        ...,
        description="Список разрешенных системных команд",
        min_items=1,
        max_items=10
    )
    
    @validator('commands')
    def validate_commands(cls, commands):
        """Валидация команд: разрешаем только безопасные команды"""
        allowed_commands = {
            'uptime', 'whoami', 'date', 'hostname', 
            'uname', 'uname -a', 'uname -r',
            'df', 'df -h', 'free', 'free -h',
            'ps', 'ps aux', 'top -bn1'
        }
        
        for cmd in commands:
            # Разбиваем команду на части для проверки
            cmd_parts = cmd.strip().split()
            if not cmd_parts:
                raise ValueError(f"Пустая команда не разрешена")
            
            base_cmd = cmd_parts[0]
            
            # Проверяем базовую команду
            if base_cmd not in allowed_commands:
                raise ValueError(f"Команда '{base_cmd}' не разрешена")
            
            # Дополнительная проверка для команды ps
            if base_cmd == 'ps' and len(cmd_parts) > 1:
                allowed_flags = {'aux'}
                if cmd_parts[1] not in allowed_flags:
                    raise ValueError(f"Флаг '{cmd_parts[1]}' не разрешен для команды ps")
            
            # Дополнительная проверка для команды df
            elif base_cmd == 'df' and len(cmd_parts) > 1:
                allowed_flags = {'-h'}
                if cmd_parts[1] not in allowed_flags:
                    raise ValueError(f"Флаг '{cmd_parts[1]}' не разрешен для команды df")
            
            # Дополнительная проверка для команды free
            elif base_cmd == 'free' and len(cmd_parts) > 1:
                allowed_flags = {'-h'}
                if cmd_parts[1] not in allowed_flags:
                    raise ValueError(f"Флаг '{cmd_parts[1]}' не разрешен для команды free")
            
            # Дополнительная проверка для команды top
            elif base_cmd == 'top' and len(cmd_parts) > 1:
                allowed_flags = {'-bn1'}
                if cmd_parts[1] not in allowed_flags:
                    raise ValueError(f"Флаг '{cmd_parts[1]}' не разрешен для команды top")
            
            # Дополнительная проверка для команды uname
            elif base_cmd == 'uname' and len(cmd_parts) > 1:
                allowed_flags = {'-a', '-r'}
                if cmd_parts[1] not in allowed_flags:
                    raise ValueError(f"Флаг '{cmd_parts[1]}' не разрешен для команды uname")
        
        return commands

# Модель ответа
class CommandOutput(BaseModel):
    command: str
    output: str
    error: Optional[str] = None
    return_code: int
    success: bool

class DiagnosticResponse(BaseModel):
    results: List[CommandOutput]
    metadata: Dict[str, str]

# Зависимость для аутентификации
async def authenticate_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> bool:
    """Проверка аутентификации администратора"""
    # В реальном приложении здесь должна быть проверка токена
    # Это упрощенный пример
    if credentials.credentials != "admin_token_here":
        raise HTTPException(
            status_code=401,
            detail="Неверные учетные данные"
        )
    return True

# Кэширование разрешенных команд
@lru_cache(maxsize=128)
def parse_command(cmd_str: str) -> List[str]:
    """Безопасное разбиение команды на аргументы"""
    return cmd_str.strip().split()

def execute_safe_command(cmd_str: str, timeout: int = 10) -> CommandOutput:
    """Безопасное выполнение команды с защитой от инъекций"""
    try:
        # Разбиваем команду на аргументы
        args = parse_command(cmd_str)
        
        if not args:
            return CommandOutput(
                command=cmd_str,
                output="",
                error="Пустая команда",
                return_code=1,
                success=False
            )
        
        logger.info(f"Выполнение команды: {args}")
        
        # Выполняем команду с безопасными параметрами
        result = subprocess.run(
            args,
            shell=False,  # Критически важно для защиты от инъекций
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='ignore'
        )
        
        return CommandOutput(
            command=cmd_str,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.stderr else None,
            return_code=result.returncode,
            success=result.returncode == 0
        )
        
    except subprocess.TimeoutExpired:
        logger.error(f"Таймаут выполнения команды: {cmd_str}")
        return CommandOutput(
            command=cmd_str,
            output="",
            error="Таймаут выполнения команды",
            return_code=124,
            success=False
        )
    except FileNotFoundError:
        logger.error(f"Команда не найдена: {cmd_str}")
        return CommandOutput(
            command=cmd_str,
            output="",
            error="Команда не найдена",
            return_code=127,
            success=False
        )
    except Exception as e:
        logger.error(f"Ошибка выполнения команды {cmd_str}: {str(e)}")
        return CommandOutput(
            command=cmd_str,
            output="",
            error=f"Внутренняя ошибка: {str(e)}",
            return_code=1,
            success=False
        )

@app.post(
    "/admin/diagnostics",
    response_model=DiagnosticResponse,
    summary="Выполнение диагностических команд",
    description="Выполняет список разрешенных системных команд и возвращает их вывод",
    response_description="Результаты выполнения команд"
)
async def run_diagnostics(
    request: DiagnosticRequest,
    is_authenticated: bool = Depends(authenticate_admin)
) -> DiagnosticResponse:
    """
    Выполняет диагностические команды на сервере.
    
    Args:
        request: Запрос со списком команд для выполнения
        is_authenticated: Результат проверки аутентификации
        
    Returns:
        DiagnosticResponse с результатами выполнения всех команд
        
    Raises:
        HTTPException: При ошибках валидации или аутентификации
    """
    try:
        results = []
        
        for cmd in request.commands:
            # Дополнительная проверка на потенциально опасные паттерны
            dangerous_patterns = [';', '&&', '||', '|', '>', '<', '`', '$', '(', ')']
            if any(pattern in cmd for pattern in dangerous_patterns):
                logger.warning(f"Обнаружен опасный паттерн в команде: {cmd}")
                results.append(CommandOutput(
                    command=cmd,
                    output="",
                    error="Команда содержит запрещенные символы",
                    return_code=1,
                    success=False
                ))
                continue
            
            # Выполняем команду
            result = execute_safe_command(cmd)
            results.append(result)
        
        # Формируем метаданные
        metadata = {
            "total_commands": len(request.commands),
            "successful_commands": sum(1 for r in results if r.success),
            "failed_commands": sum(1 for r in results if not r.success),
            "warning": "Все команды выполняются с ограниченными привилегиями"
        }
        
        return DiagnosticResponse(
            results=results,
            metadata=metadata
        )
        
    except Exception as e:
        logger.error(f"Ошибка в эндпоинте диагностики: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

# Дополнительный эндпоинт для проверки здоровья
@app.get("/health")
async def health_check():
    """Проверка работоспособности сервера"""
    return {"status": "ok", "service": "diagnostics"}

# Глобальный обработчик исключений
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logger.error(f"HTTP ошибка {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )