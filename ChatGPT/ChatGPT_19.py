import json
import logging
from typing import Any, Dict, Optional

import requests


# =========================
# Конфигурация логирования
# =========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =========================
# Исключения домена
# =========================

class LlmIntegrationError(Exception):
    """Базовое исключение интеграции с LLM."""


class LlmApiConnectionError(LlmIntegrationError):
    """Ошибка соединения с внешним LLM API."""


class LlmApiResponseError(LlmIntegrationError):
    """Ошибка формата или содержания ответа LLM."""


# =========================
# Конфигурация сервиса
# =========================

class LlmConfig:
    """
    Конфигурация LLM API.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 10,
    ) -> None:
        self.api_url: str = api_url
        self.api_key: str = api_key
        self.model: str = model
        self.timeout_seconds: int = timeout_seconds


# =========================
# Системный промпт
# =========================

class SystemPromptTemplate:
    """
    Шаблон системного промпта.
    """

    TEMPLATE: str = (
        "You are an expert assistant.\n"
        "Follow these rules strictly:\n"
        "- Answer clearly and concisely\n"
        "- Do not hallucinate facts\n"
        "- Use structured reasoning internally\n\n"
        "User input:\n"
        "{user_input}\n\n"
        "Final answer:"
    )

    @classmethod
    def build(cls, user_input: str) -> str:
        """
        Встраивает пользовательский ввод в шаблон.
        """
        return cls.TEMPLATE.format(user_input=user_input.strip())


# =========================
# HTTP-клиент LLM API
# =========================

class LlmHttpClient:
    """
    Низкоуровневый HTTP-клиент для общения с LLM API.
    """

    def __init__(self, config: LlmConfig) -> None:
        self._config = config

    def send_prompt(self, prompt: str) -> Dict[str, Any]:
        """
        Отправляет промпт в LLM API и возвращает сырой JSON-ответ.
        """
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": prompt},
            ],
        }

        try:
            response = requests.post(
                self._config.api_url,
                headers=headers,
                json=payload,
                timeout=self._config.timeout_seconds,
            )
        except requests.RequestException as exc:  # noqa: BLE001
            logger.exception("LLM API connection error")
            raise LlmApiConnectionError(str(exc)) from exc

        if response.status_code != 200:
            raise LlmApiResponseError(
                f"LLM API returned {response.status_code}: {response.text}"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise LlmApiResponseError("Invalid JSON response") from exc


# =========================
# Очистка и нормализация ответа
# =========================

class LlmResponseCleaner:
    """
    Очистка и нормализация ответа LLM.
    """

    @staticmethod
    def extract_text(api_response: Dict[str, Any]) -> str:
        """
        Извлекает текст ответа из OpenAI-совместимого JSON.
        """
        try:
            raw_text: str = api_response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmApiResponseError("Unexpected response structure") from exc

        return LlmResponseCleaner._normalize(raw_text)

    @staticmethod
    def _normalize(text: str) -> str:
        """
        Удаляет лишние пробелы и технические маркеры.
        """
        return text.strip()


# =========================
# Основной сервис-интегратор
# =========================

class LlmIntegrationService:
    """
    Высокоуровневый сервис интеграции с LLM.
    """

    def __init__(self, client: LlmHttpClient) -> None:
        self._client = client

    def process_user_input(self, user_input: str) -> str:
        """
        Основной сценарий:
        1. Формирование системного промпта
        2. Отправка в LLM API
        3. Очистка и возврат ответа
        """
        if not user_input.strip():
            raise ValueError("User input must not be empty")

        prompt: str = SystemPromptTemplate.build(user_input)

        logger.info("Sending prompt to LLM")
        raw_response = self._client.send_prompt(prompt)

        return LlmResponseCleaner.extract_text(raw_response)


# =========================
# Пример использования
# =========================

def example_usage() -> None:
    """
    Демонстрация использования сервиса.
    """
    config = LlmConfig(
        api_url="https://api.openai.com/v1/chat/completions",
        api_key="YOUR_API_KEY",
        model="gpt-4",
    )

    client = LlmHttpClient(config)
    service = LlmIntegrationService(client)

    result = service.process_user_input(
        "Explain dependency inversion principle in simple terms."
    )

    print(result)
