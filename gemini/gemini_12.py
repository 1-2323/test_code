import subprocess
import shlex
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

class CommandResult:
    """Типизированный объект для хранения результата выполнения команды."""
    def __init__(self, command: str, stdout: str, stderr: str, return_code: int):
        self.command = command
        self.stdout = stdout.strip()
        self.stderr = stderr.strip()
        self.return_code = return_code
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует результат в словарь для JSON-ответа."""
        return {
            "command": self.command,
            "status": "success" if self.return_code == 0 else "error",
            "output": self.stdout if self.return_code == 0 else self.stderr,
            "return_code": self.return_code,
            "executed_at": self.timestamp
        }

class ServerHealthTool:
    """
    Сервис диагностики сервера.
    Позволяет безопасно выполнять ограниченный набор системных команд.
    """

    # Белый список разрешенных команд для предотвращения RCE атак
    ALLOWED_COMMANDS = {
        "ping": ["ping", "-c", "4", "8.8.8.8"],
        "uptime": ["uptime"],
        "disk_usage": ["df", "-h"],
        "memory": ["free", "-m"],
        "cpu_load": ["top", "-bn1"],
    }

    def __init__(self, timeout: int = 5):
        """
        :param timeout: Максимальное время выполнения команды в секундах.
        """
        self.timeout = timeout

    def _safe_execute(self, cmd_key: str) -> CommandResult:
        """
        Внутренний метод для безопасного запуска процесса.
        Использует subprocess.run без shell=True.
        """
        if cmd_key not in self.ALLOWED_COMMANDS:
            return CommandResult(cmd_key, "", "Command not allowed", 1)

        full_cmd = self.ALLOWED_COMMANDS[cmd_key]

        try:
            # Запуск процесса с ограничением по времени и захватом потоков вывода
            process = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False  # Мы сами обрабатываем return_code
            )
            return CommandResult(
                command=cmd_key,
                stdout=process.stdout,
                stderr=process.stderr,
                return_code=process.return_code
            )
        except subprocess.TimeoutExpired:
            return CommandResult(cmd_key, "", "Command timed out", 124)
        except Exception as e:
            return CommandResult(cmd_key, "", f"Execution error: {str(e)}", 1)

    def run_diagnostics(self, requested_commands: List[str]) -> str:
        """
        Основной эндпоинт для запуска списка команд.
        Принимает список ключей, исполняет их и возвращает JSON.
        """
        results = []
        
        for cmd_key in requested_commands:
            result_obj = self._safe_execute(cmd_key)
            results.append(result_obj.to_dict())

        # Формируем итоговый отчет
        report = {
            "server_report": {
                "generated_at": datetime.now().isoformat(),
                "results": results
            }
        }
        
        return json.dumps(report, indent=4, ensure_ascii=False)

# --- Пример интеграции (Эмуляция веб-запроса) ---

if __name__ == "__main__":
    tool = ServerHealthTool()

    # Имитация данных из POST-запроса веб-интерфейса
    user_request = ["uptime", "memory", "invalid_cmd", "disk_usage"]

    print("--- Запуск системной диагностики ---")
    json_response = tool.run_diagnostics(user_request)
    
    # Вывод результата (то, что получит фронтенд)
    print(json_response)