import subprocess
from typing import Dict, List, Callable, Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict


# =========================
# Pydantic СХЕМЫ
# =========================

class CommandRequest(BaseModel):
    """
    Запрос на выполнение диагностических команд.
    """
    commands: List[str] = Field(min_length=1, max_length=5)

    model_config = ConfigDict(extra="forbid")


class CommandResult(BaseModel):
    command: str
    output: str
    success: bool


class HealthCheckResponse(BaseModel):
    results: List[CommandResult]


# =========================
# БЕЛЫЙ СПИСОК КОМАНД
# =========================

def cmd_uptime() -> str:
    result = subprocess.run(
        ["uptime"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def cmd_ping_localhost() -> str:
    result = subprocess.run(
        ["ping", "-c", "1", "127.0.0.1"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def cmd_disk_usage() -> str:
    result = subprocess.run(
        ["df", "-h"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


ALLOWED_COMMANDS: Dict[str, Callable[[], str]] = {
    "uptime": cmd_uptime,
    "ping_localhost": cmd_ping_localhost,
    "disk_usage": cmd_disk_usage,
}


# =========================
# СЕРВИС ДИАГНОСТИКИ
# =========================

class ServerHealthTool:
    """
    Утилита диагностики сервера.
    Выполняет только разрешённые команды.
    """

    def execute(self, commands: List[str]) -> List[CommandResult]:
        results: List[CommandResult] = []

        for command in commands:
            if command not in ALLOWED_COMMANDS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Команда '{command}' не разрешена",
                )

            try:
                output = ALLOWED_COMMANDS[command]()
                results.append(
                    CommandResult(
                        command=command,
                        output=output,
                        success=True,
                    )
                )
            except Exception as exc:
                results.append(
                    CommandResult(
                        command=command,
                        output=str(exc),
                        success=False,
                    )
                )

        return results


# =========================
# FASTAPI ПРИЛОЖЕНИЕ
# =========================

app = FastAPI(
    title="Server Health Tool",
    version="1.0.0",
    description="Инструмент диагностики сервера",
)

health_tool = ServerHealthTool()


# =========================
# ENDPOINT
# =========================

@app.post(
    "/admin/server/health",
    response_model=HealthCheckResponse,
)
def check_server_health(request: CommandRequest) -> HealthCheckResponse:
    """
    Эндпоинт диагностики сервера.
    """
    results = health_tool.execute(request.commands)
    return HealthCheckResponse(results=results)
