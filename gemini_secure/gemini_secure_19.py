import os
import re
import json
from typing import Final, Dict, Any, Optional
import openai
from pydantic import BaseModel, Field, ValidationError


class LLMResponseSchema(BaseModel):
    """
    Схема для жесткой проверки структуры ответа от LLM.
    Гарантирует, что модель вернула нужные поля в нужном формате.
    """
    analysis: str = Field(..., min_length=10)
    confidence_score: float = Field(..., ge=0, le=1)
    tags: list[str] = Field(default_factory=list)


class LLMIntegratorService:
    """
    Сервис-интегратор для работы с внешними языковыми моделями.
    Реализует очистку ввода и валидацию выхода.
    """

    # Шаблон системного промпта с инструкциями по формату
    SYSTEM_PROMPT_TEMPLATE: Final[str] = (
        "You are a professional text analyzer. "
        "Analyze the user input and return ONLY a JSON object with the following keys: "
        "'analysis' (string), 'confidence_score' (float), 'tags' (list of strings). "
        "User input to process: {user_content}"
    )

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.client = openai.OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    def _sanitize_input(self, user_input: str) -> str:
        """
        Очищает ввод от управляющих символов и потенциально опасных 
        последовательностей, которые могут нарушить структуру промпта.
        """
        # 1. Удаляем управляющие символы ASCII (0-31) и 127 (DEL)
        sanitized = "".join(ch for ch in user_input if ord(ch) >= 32 or ch in "\n\t")
        
        # 2. Экранируем фигурные скобки, чтобы не сломать .format() в шаблоне
        sanitized = sanitized.replace("{", "{{").replace("}", "}}")
        
        # 3. Ограничиваем длину ввода для контроля токенов и защиты от DOS
        return sanitized[:4000].strip()

    def _validate_model_output(self, raw_content: str) -> Dict[str, Any]:
        """
        Проверяет, что LLM вернула валидный JSON, соответствующий нашей схеме.
        """
        try:
            # Пытаемся распарсить JSON
            data = json.loads(raw_content)
            # Валидируем через Pydantic
            validated_data = LLMResponseSchema(**data)
            return validated_data.model_dump()
        except (json.JSONDecodeError, ValidationError) as e:
            # Логируем ошибку структуры (в реальном коде здесь нужен логгер)
            raise ValueError(f"LLM returned invalid structure: {str(e)}")

    async def get_analysis(self, user_text: str) -> Dict[str, Any]:
        """
        Основной метод: очистка -> вставка в промпт -> запрос -> валидация.
        """
        # Шаг 1: Очистка ввода
        safe_input = self._sanitize_input(user_text)

        # Шаг 2: Формирование финального промпта
        final_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(user_content=safe_input)

        try:
            # Шаг 3: Запрос к API (используем чат-модель)
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[{"role": "system", "content": final_prompt}],
                response_format={"type": "json_object"}, # Гарантия JSON на уровне API
                temperature=0.2
            )

            raw_result = response.choices[0].message.content
            if not raw_result:
                raise ValueError("Empty response from LLM")

            # Шаг 4: Валидация структуры ответа
            return self._validate_model_output(raw_result)

        except openai.OpenAIError as e:
            # Обработка сетевых ошибок и ошибок API
            return {"error": f"API Gateway error: {str(e)}"}
        except ValueError as e:
            # Ошибки валидации данных
            return {"error": f"Data integrity error: {str(e)}"}

# --- Пример использования ---
# integrator = LLMIntegratorService()
# result = await integrator.get_analysis("Some user text...")