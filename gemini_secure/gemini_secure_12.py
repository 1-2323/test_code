import subprocess
from typing import List, Dict, Any, Final, Optional
from pydantic import BaseModel, Field, validator
from fastapi import FastAPI, HTTPException, status


class CommandRequest(BaseModel):
    """
    Схема валидации входящего запроса на диагностику.
    Принимает имя команды из предопределенного списка.
    """
    command_name: str = Field(..., description="Alias of the allowed command")
    target: Optional[str] = Field(None, description="Optional target (e.g. IP or hostname)")

    @validator("target")
    def sanitize_target(cls, v: Optional[str]) -> Optional[str]:
        """Очистка цели от спецсимволов, которые могут быть интерпретированы."""
        if v is None:
            return v
        # Разрешаем только алфавитно-цифровые символы, точки и дефисы (для IP/хостов)
        import re
        if not re.match(r"^[a-zA-Z0-9.-]+$", v):
            raise ValueError("Invalid characters in target")
        return v


class ServerHealthTool:
    """
    Инструмент диагностики сервера с жестким белым списком команд.
    Исключает использование shell=True для защиты от инъекций.
    """

    # Белый список разрешенных команд и их базовых аргументов
    # Формат: {alias: [executable, base_args...]}
    ALLOWED_COMMANDS: Final[Dict[str, List[str]]] = {
        "ping": ["/usr/bin/ping", "-c", "4"],
        "uptime": ["/usr/bin/uptime"],
        "disk_free": ["/usr/bin/df", "-h"],
        "memory_usage": ["/usr/bin/free", "-m"]
    }

    def execute_diagnostic(self, command_alias: str, target: Optional[str] = None) -> Dict[str, Any]:
        """
        Безопасно исполняет команду из белого списка.
        
        :param command_alias: Псевдоним команды из ALLOWED_COMMANDS.
        :param target: Дополнительный аргумент (например, IP для ping).
        :return: Словарь с результатом выполнения или ошибкой.
        """
        # 1. Проверка наличия команды в белом списке
        if command_alias not in self.ALLOWED_COMMANDS:
            raise ValueError(f"Command '{command_alias}' is not permitted.")

        # 2. Сборка списка аргументов (без участия shell)
        full_command = list(self.ALLOWED_COMMANDS[command_alias])
        if target and command_alias == "ping":
            full_command.append(target)

        try:
            # 3. Выполнение команды
            # shell=False гарантирует, что аргументы не будут интерпретированы оболочкой
            process = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False
            )

            return {
                "command": command_alias,
                "exit_code": process.returncode,
                "stdout": process.stdout.strip(),
                "stderr": process.stderr.strip(),
                "status": "success" if process.returncode == 0 else "error"
            }

        except subprocess.TimeoutExpired:
            return {"error": "Command timed out", "status": "timeout"}
        except Exception as e:
            return {"error": str(e), "status": "internal_error"}


# --- API Interface ---

app = FastAPI(title="Server Health Diagnostic API")
health_tool = ServerHealthTool()

@app.post("/diagnostics/run", status_code=status.HTTP_200_OK)
async def run_diagnostic(request: CommandRequest) -> Dict[str, Any]:
    """
    Эндпоинт для запуска системной диагностики.
    """
    try:
        result = health_tool.execute_diagnostic(
            request.command_name, 
            request.target
        )
        
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result)
            
        return result

    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="An unexpected error occurred")