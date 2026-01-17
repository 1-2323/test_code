import httpx
import json
import logging
from typing import Dict, Any, Optional

# Настройка логирования для мониторинга запросов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LLMIntegrator")

class LLMIntegratorService:
    """
    Сервис-интегратор для работы с Large Language Models (LLM).
    Обеспечивает инъекцию промптов, работу с внешним API и постобработку ответов.
    """

    SYSTEM_TEMPLATE = """
    Ты — экспертный ассистент по анализу данных. 
    Твоя задача: проанализировать ввод пользователя и вернуть строго структурированный ответ.
    Контекст: Работай только с предоставленными фактами. 
    Формат: Если не указано иное, возвращай текст без лишних вступлений.
    
    ПОЛЬЗОВАТЕЛЬСКИЙ ВВОД:
    {user_input}
    """

    def __init__(self, api_key: str, model: str = "gpt-4", base_url: str = "https://api.openai.com/v1/chat/completions"):
        """
        :param api_key: Ключ доступа к API.
        :param model: Идентификатор используемой модели.
        :param base_url: URL эндпоинта генерации текста.
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _prepare_payload(self, user_input: str) -> Dict[str, Any]:
        """Вставляет ввод пользователя в системный шаблон и формирует JSON-тело запроса."""
        full_prompt = self.SYSTEM_TEMPLATE.format(user_input=user_input)
        
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Вы — полезный помощник."},
                {"role": "user", "content": full_prompt}
            ],
            "temperature": 0.7
        }

    def _clean_response(self, raw_text: str) -> str:
        """
        Очищает ответ от артефактов LLM (лишние пробелы, markdown-разметка кода).
        """
        cleaned = raw_text.strip()
        # Удаление обратных кавычек, если модель вернула блок кода
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        
        return cleaned

    async def generate_response(self, user_input: str) -> Optional[str]:
        """
        Основной цикл обработки:
        1. Формирование промпта.
        2. Отправка асинхронного POST-запроса.
        3. Обработка JSON и очистка результата.
        """
        payload = self._prepare_payload(user_input)
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                logger.info(f"Отправка запроса к LLM ({self.model})...")
                response = await client.post(
                    self.base_url, 
                    headers=self.headers, 
                    json=payload
                )
                
                # Проверка статуса ответа
                response.raise_for_status()
                data = response.json()
                
                # Извлечение текста из структуры OpenAI-like API
                raw_content = data['choices'][0]['message']['content']
                
                return self._clean_response(raw_content)

            except httpx.HTTPStatusError as e:
                logger.error(f"Ошибка API: {e.response.status_code} - {e.response.text}")
                return None
            except (KeyError, IndexError) as e:
                logger.error(f"Ошибка парсинга ответа: {str(e)}")
                return None
            except Exception as e:
                logger.error(f"Непредвиденная ошибка: {str(e)}")
                raise

# --- Пример использования ---

async def main():
    # Инициализация (API ключ должен быть в переменных окружения)
    API_TOKEN = "sk-example-key-12345"
    service = LLMIntegratorService(api_key=API_TOKEN)

    prompt = "Напиши краткий отчет по продажам: 100 юнитов, выручка 5000$."
    
    print("--- Запрос к LLM ---")
    # Для запуска требуется реальный API ключ
    # result = await service.generate_response(prompt)
    # print(f"Ответ: {result}")
    print("(Пример кода готов к работе)")

if __name__ == "__main__":
    import asyncio
    # asyncio.run(main())