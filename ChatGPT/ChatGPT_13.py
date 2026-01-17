import subprocess
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# =========================
# Pydantic-модели
# =========================

class CommandRequest(BaseModel):
    """
    Запрос на выполнение диагностических команд.
    """
    commands: List[str] = Field(
        ...,
        description="Список диагностических команд (например: ping, uptime)",
        min_items=1,
    )


class CommandResult(BaseModel):
    """
    Результат выполнения одной команды.
    """
    command: str
    exit_code: int
    output: str


class HealthCheckResponse(BaseModel):
    """
    Ответ сервиса диагностики сервера.
    """
    results: List[CommandResult]


# =========================
# Сервис диагностики
# =========================

class ServerHealthTool:
    """
    Сервис для выполнения разрешённых системных команд
    и возврата их результатов.
    """

    # Белый список допустимых команд
    ALLOWED_COMMANDS: Dict[str, List[str]] = {
        "uptime": ["uptime"],
        "ping": ["ping", "-c", "4", "8.8.8.8"],
        "df": ["df", "-h"],
    }

    def execute_commands(self, commands: List[str]) -> List[CommandResult]:
        """
        Выполняет список диагностических команд.

        Алгоритм:
        1. Проверка, что команда разрешена
        2. Безопасное выполнение через subprocess
        3. Сбор stdout / stderr
        """
        results: List[CommandResult] = []

        for command_name in commands:
            if command_name not in self.ALLOWED_COMMANDS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Command '{command_name}' is not allowed",
                )

            result = self._execute_single(command_name)
            results.append(result)

        return results

    def _execute_single(self, command_name: str) -> CommandResult:
        """
        Выполняет одну разрешённую команду.
        """
        command: List[str] = self.ALLOWED_COMMANDS[command_name]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            output: str = (
                completed.stdout.strip()
                if completed.stdout
                else completed.stderr.strip()
            )

            return CommandResult(
                command=command_name,
                exit_code=completed.returncode,
                output=output,
            )

        except Exception as exc:  # noqa: BLE001
            return CommandResult(
                command=command_name,
                exit_code=1,
                output=f"Execution failed: {exc}",
            )


# =========================
# FastAPI-приложение
# =========================

app = FastAPI(title="Server Health Tool")


@app.post("/health/diagnostics", response_model=HealthCheckResponse)
def run_diagnostics(request: CommandRequest) -> HealthCheckResponse:
    """
    Эндпоинт диагностики сервера.

    Принимает список команд и возвращает
    результаты их выполнения в формате JSON.
    """
    tool = ServerHealthTool()
    results = tool.execute_commands(request.commands)

    return HealthCheckResponse(results=results)
