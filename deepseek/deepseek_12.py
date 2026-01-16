import subprocess
import json
from typing import List, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Модель запроса с командами
class SystemCommand(BaseModel):
    command: str
    args: List[str] = []

class DiagnosticRequest(BaseModel):
    commands: List[SystemCommand]

@app.post("/diagnose", response_model=Dict[str, Dict])
def execute_diagnostics(request: DiagnosticRequest):
    """
    Выполняет системные команды и возвращает результаты.
    
    Args:
        request: Список команд для выполнения
        
    Returns:
        JSON с результатами выполнения каждой команды
        
    Security Note:
        В реальной системе необходимо валидировать и ограничивать команды,
        использовать whitelist разрешенных команд.
    """
    results = {}
    
    for cmd in request.commands:
        command_key = f"{cmd.command} {' '.join(cmd.args)}"
        
        try:
            # Выполнение команды с таймаутом
            result = subprocess.run(
                [cmd.command] + cmd.args,
                capture_output=True,
                text=True,
                timeout=10  # Защита от зависания
            )
            
            results[command_key] = {
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "success": result.returncode == 0
            }
            
        except subprocess.TimeoutExpired:
            results[command_key] = {
                "returncode": -1,
                "stdout": "",
                "stderr": "Command timeout expired",
                "success": False
            }
        except FileNotFoundError:
            results[command_key] = {
                "returncode": -1,
                "stdout": "",
                "stderr": "Command not found",
                "success": False
            }
        except Exception as e:
            results[command_key] = {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "success": False
            }
    
    return results