import subprocess
import json
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import asyncio
from concurrent.futures import ThreadPoolExecutor

router = APIRouter()

# Модель для запроса
class DiagnosticCommand(BaseModel):
    command: str = Field(..., description="Системная команда для выполнения")
    timeout: Optional[int] = Field(30, ge=1, le=300, description="Таймаут выполнения в секундах")
    args: Optional[List[str]] = Field([], description="Аргументы команды")

class DiagnosticsRequest(BaseModel):
    commands: List[DiagnosticCommand] = Field(..., max_items=10, description="Список команд для выполнения")
    parallel: Optional[bool] = Field(True, description="Выполнять команды параллельно")

class CommandResult(BaseModel):
    command: str
    full_command: str
    return_code: int
    stdout: str
    stderr: str
    success: bool
    error: Optional[str] = None
    execution_time: float

class DiagnosticsResponse(BaseModel):
    results: List[CommandResult]
    total_commands: int
    successful_commands: int
    failed_commands: int

# Список разрешенных команд для безопасности
ALLOWED_COMMANDS = {
    "uptime": ["uptime"],
    "memory": ["free", "-h"],
    "disk": ["df", "-h"],
    "cpu": ["top", "-bn1"],
    "processes": ["ps", "aux", "--sort=-%cpu"],
    "network": ["ss", "-tuln"],
    "load": ["cat", "/proc/loadavg"],
    "date": ["date"],
    "who": ["who"],
    "dmesg": ["dmesg", "-T", "-l", "err,crit,alert,emerg"]
}

def is_command_allowed(command: str, args: List[str]) -> bool:
    """Проверка, разрешена ли команда к выполнению"""
    if command in ALLOWED_COMMANDS:
        # Проверяем базовую команду
        allowed_base = ALLOWED_COMMANDS[command][0]
        if allowed_base != command.split()[0] if ' ' in command else command:
            return False
        
        # Проверяем аргументы
        allowed_args = ALLOWED_COMMANDS[command][1:]
        for arg in args:
            if arg.startswith('-') and arg not in allowed_args:
                # Проверяем только флаги, значения флагов пропускаем
                if not any(allowed_arg.startswith(arg.split('=')[0]) for allowed_arg in allowed_args):
                    return False
        return True
    return False

def execute_single_command(diagnostic_command: DiagnosticCommand) -> CommandResult:
    """Выполнение одной системной команды"""
    import time
    start_time = time.time()
    
    try:
        # Разделяем команду на части
        cmd_parts = diagnostic_command.command.split()
        base_command = cmd_parts[0]
        cmd_args = cmd_parts[1:] + diagnostic_command.args
        
        # Проверяем разрешена ли команда
        if not is_command_allowed(base_command, cmd_args):
            raise PermissionError(f"Команда '{diagnostic_command.command}' не разрешена для выполнения")
        
        # Формируем полную команду
        full_command = [base_command] + cmd_args
        
        # Выполняем команду с таймаутом
        result = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            timeout=diagnostic_command.timeout,
            shell=False
        )
        
        execution_time = time.time() - start_time
        
        return CommandResult(
            command=diagnostic_command.command,
            full_command=" ".join(full_command),
            return_code=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            success=result.returncode == 0,
            execution_time=execution_time
        )
        
    except subprocess.TimeoutExpired:
        execution_time = time.time() - start_time
        return CommandResult(
            command=diagnostic_command.command,
            full_command=diagnostic_command.command,
            return_code=-1,
            stdout="",
            stderr="",
            success=False,
            error="Command timeout expired",
            execution_time=execution_time
        )
    except PermissionError as e:
        execution_time = time.time() - start_time
        return CommandResult(
            command=diagnostic_command.command,
            full_command=diagnostic_command.command,
            return_code=-1,
            stdout="",
            stderr="",
            success=False,
            error=str(e),
            execution_time=execution_time
        )
    except Exception as e:
        execution_time = time.time() - start_time
        return CommandResult(
            command=diagnostic_command.command,
            full_command=diagnostic_command.command,
            return_code=-1,
            stdout="",
            stderr="",
            success=False,
            error=f"Execution error: {str(e)}",
            execution_time=execution_time
        )

@router.post("/admin/diagnostics", response_model=DiagnosticsResponse)
async def run_diagnostics(request: DiagnosticsRequest):
    """
    Выполняет системные диагностические команды и возвращает их вывод
    """
    if not request.commands:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Список команд не может быть пустым"
        )
    
    if len(request.commands) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Максимальное количество команд - 10"
        )
    
    try:
        results = []
        
        if request.parallel:
            # Параллельное выполнение команд
            with ThreadPoolExecutor(max_workers=min(len(request.commands), 5)) as executor:
                loop = asyncio.get_event_loop()
                tasks = [
                    loop.run_in_executor(executor, execute_single_command, cmd)
                    for cmd in request.commands
                ]
                results = await asyncio.gather(*tasks)
        else:
            # Последовательное выполнение команд
            for cmd in request.commands:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, execute_single_command, cmd
                )
                results.append(result)
        
        # Подсчет статистики
        successful = sum(1 for r in results if r.success)
        
        return DiagnosticsResponse(
            results=results,
            total_commands=len(results),
            successful_commands=successful,
            failed_commands=len(results) - successful
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при выполнении диагностики: {str(e)}"
        )