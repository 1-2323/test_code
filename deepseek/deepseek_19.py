import json
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
import aiohttp
import asyncio
from dataclasses import dataclass
from enum import Enum


class LLMProvider(Enum):
    """Провайдеры LLM"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    CUSTOM = "custom"


@dataclass
class LLMResponse:
    """Ответ от LLM"""
    content: str
    model: str
    tokens_used: int
    finish_reason: str
    raw_response: Dict[str, Any]


@dataclass
class PromptTemplate:
    """Шаблон промпта"""
    template: str
    variables: List[str]
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 1000


class LLMClient(ABC):
    """Абстрактный клиент для работы с LLM"""
    
    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> LLMResponse:
        """Сгенерировать ответ от LLM"""
        pass


class OpenAILLMClient(LLMClient):
    """Клиент для OpenAI API"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-3.5-turbo"
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def generate_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> LLMResponse:
        """Сгенерировать ответ через OpenAI API"""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        async with self.session.post(
            f"{self.base_url}/chat/completions",
            json=payload
        ) as response:
            response_data = await response.json()
            
            if response.status != 200:
                error_message = response_data.get('error', {}).get('message', 'Unknown error')
                raise Exception(f"OpenAI API error: {error_message}")
            
            completion = response_data['choices'][0]['message']['content']
            
            return LLMResponse(
                content=completion,
                model=self.default_model,
                tokens_used=response_data['usage']['total_tokens'],
                finish_reason=response_data['choices'][0]['finish_reason'],
                raw_response=response_data
            )


class LLMIntegratorService:
    """Сервис-интегратор с LLM"""
    
    def __init__(
        self,
        llm_client: LLMClient,
        prompt_templates: Dict[str, PromptTemplate]
    ):
        self.llm_client = llm_client
        self.prompt_templates = prompt_templates
    
    def render_template(
        self,
        template_name: str,
        variables: Dict[str, Any]
    ) -> str:
        """
        Рендеринг шаблона промпта с переменными
        
        Args:
            template_name: Имя шаблона
            variables: Словарь переменных для подстановки
            
        Returns:
            Отрендеренный промпт
        """
        if template_name not in self.prompt_templates:
            raise ValueError(f"Template '{template_name}' not found")
        
        template = self.prompt_templates[template_name]
        
        # Проверяем, что все необходимые переменные предоставлены
        missing_vars = [var for var in template.variables if var not in variables]
        if missing_vars:
            raise ValueError(f"Missing template variables: {missing_vars}")
        
        # Рендерим шаблон
        rendered = template.template
        for var_name, var_value in variables.items():
            placeholder = f"{{{var_name}}}"
            rendered = rendered.replace(placeholder, str(var_value))
        
        return rendered
    
    async def process_with_llm(
        self,
        template_name: str,
        variables: Dict[str, Any],
        extraction_pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Обработать запрос с помощью LLM
        
        Args:
            template_name: Имя шаблона промпта
            variables: Переменные для подстановки в шаблон
            extraction_pattern: Паттерн для извлечения структурированных данных
            
        Returns:
            Словарь с результатами
        """
        try:
            # 1. Рендерим промпт
            user_prompt = self.render_template(template_name, variables)
            template = self.prompt_templates[template_name]
            
            # 2. Отправляем запрос к LLM
            response = await self.llm_client.generate_response(
                prompt=user_prompt,
                system_prompt=template.system_prompt,
                temperature=template.temperature,
                max_tokens=template.max_tokens
            )
            
            # 3. Обрабатываем ответ
            result = {
                "success": True,
                "response": response.content,
                "model": response.model,
                "tokens_used": response.tokens_used,
                "template_used": template_name
            }
            
            # 4. Извлекаем структурированные данные, если задан паттерн
            if extraction_pattern:
                extracted_data = self._extract_structured_data(
                    response.content,
                    extraction_pattern
                )
                result["extracted_data"] = extracted_data
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "template_used": template_name
            }
    
    def _extract_structured_data(
        self,
        response_text: str,
        pattern: str
    ) -> Dict[str, Any]:
        """
        Извлечение структурированных данных из текстового ответа
        
        В реальном приложении здесь могла бы быть более сложная логика,
        например, использование regex или вызов LLM для парсинга
        """
        # Простая реализация для примера
        # В реальности здесь может быть парсинг JSON или другой формат
        if pattern == "json":
            try:
                # Пытаемся найти JSON в тексте
                lines = response_text.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if (line.startswith('{') and line.endswith('}')) or \
                       (line.startswith('[') and line.endswith(']')):
                        return json.loads(line)
            except json.JSONDecodeError:
                pass
        
        # Возвращаем чистый текст, если не удалось извлечь структуру
        return {"text": response_text.strip()}
    
    def add_template(
        self,
        name: str,
        template: PromptTemplate
    ) -> None:
        """Добавить новый шаблон промпта"""
        self.prompt_templates[name] = template
    
    def remove_template(self, name: str) -> None:
        """Удалить шаблон промпта"""
        if name in self.prompt_templates:
            del self.prompt_templates[name]


# Примеры шаблонов промптов
DEFAULT_TEMPLATES = {
    "text_analysis": PromptTemplate(
        system_prompt="Ты - профессиональный аналитик текста. Твоя задача - анализировать предоставленные тексты и давать развернутые ответы.",
        template="""
        Проанализируй следующий текст:
        
        {text}
        
        Пожалуйста, предоставь анализ по следующим пунктам:
        1. Основная тема текста
        2. Ключевые идеи
        3. Тональность текста
        4. Рекомендации по улучшению (если применимо)
        
        Ответ предоставь в формате JSON.
        """,
        variables=["text"],
        temperature=0.3,
        max_tokens=500
    ),
    
    "code_review": PromptTemplate(
        system_prompt="Ты - опытный разработчик, проводящий код-ревью. Будь конструктивным и давай конкретные рекомендации.",
        template="""
        Проведи код-ревью для следующего фрагмента кода на языке {language}:
        
        ```{language}
        {code}
        ```
        
        Оцени:
        1. Качество кода
        2. Потенциальные ошибки
        3. Возможности для оптимизации
        4. Соответствие best practices
        
        Предоставь ответ в виде структурированного списка.
        """,
        variables=["language", "code"],
        temperature=0.2,
        max_tokens=800
    ),
    
    "content_generation": PromptTemplate(
        system_prompt="Ты - креативный копирайтер. Создавай уникальный и интересный контент.",
        template="""
        Создай контент на тему "{topic}" в стиле "{style}".
        
        Требования:
        - Длина: {length} слов
        - Целевая аудитория: {audience}
        - Ключевые слова для включения: {keywords}
        
        Пожалуйста, предоставь только готовый контент без дополнительных комментариев.
        """,
        variables=["topic", "style", "length", "audience", "keywords"],
        temperature=0.8,
        max_tokens=1500
    )
}


# Пример использования
async def main_example():
    """Пример использования LLM интегратора"""
    
    # Инициализация клиента (в реальном приложении API ключ нужно хранить в secrets)
    llm_client = OpenAILLMClient(
        api_key="your-api-key-here",  # Заменить на реальный ключ
        default_model="gpt-3.5-turbo"
    )
    
    # Создание сервиса с шаблонами по умолчанию
    llm_service = LLMIntegratorService(
        llm_client=llm_client,
        prompt_templates=DEFAULT_TEMPLATES
    )
    
    # Добавление пользовательского шаблона
    custom_template = PromptTemplate(
        system_prompt="Ты - помощник по изучению языков.",
        template="""
        Объясни значение слова "{word}" на языке {language}.
        
        Предоставь:
        1. Перевод на русский
        2. Пример использования в предложении
        3. Синонимы (если есть)
        
        Ответ должен быть кратким и информативным.
        """,
        variables=["word", "language"],
        temperature=0.5,
        max_tokens=300
    )
    
    llm_service.add_template("language_learning", custom_template)
    
    # Пример запроса для анализа текста
    variables = {
        "text": "Искусственный интеллект революционизирует различные отрасли, включая медицину, образование и бизнес."
    }
    
    async with llm_client:
        result = await llm_service.process_with_llm(
            template_name="text_analysis",
            variables=variables,
            extraction_pattern="json"
        )
    
    if result["success"]:
        print("Анализ успешно выполнен:")
        print(f"Использовано токенов: {result['tokens_used']}")
        print(f"Ответ: {result['response'][:200]}...")
        
        if "extracted_data" in result:
            print(f"Извлеченные данные: {json.dumps(result['extracted_data'], indent=2, ensure_ascii=False)}")
    else:
        print(f"Ошибка: {result['error']}")


if __name__ == "__main__":
    # Для запуска примера
    # asyncio.run(main_example())
    print("Для работы с LLM требуется реальный API ключ OpenAI")