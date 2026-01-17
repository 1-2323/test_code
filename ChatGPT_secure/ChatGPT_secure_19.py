import json
import re
from typing import Any, Dict

import requests


# =========================
# EXCEPTIONS
# =========================

class LLMIntegrationError(Exception):
    pass


class InvalidLLMResponseError(LLMIntegrationError):
    pass


# =========================
# INPUT SANITIZATION
# =========================

_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_user_input(value: str) -> str:
    """
    Удаляет управляющие символы из пользовательского ввода
    перед вставкой в системный промпт.
    """
    return _CONTROL_CHARS_PATTERN.sub("", value).strip()


# =========================
# LLM CLIENT
# =========================

class LLMIntegrator:
    """
    Сервис-интегратор с внешней LLM (например, OpenAI).
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout_seconds: int = 10,
    ) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._timeout = timeout_seconds

    def generate_response(self, user_input: str) -> str:
        """
        Формирует системный промпт, отправляет запрос к LLM
        и возвращает очищенный и проверенный ответ.
        """
        sanitized_input = sanitize_user_input(user_input)
        prompt = self._build_prompt(sanitized_input)

        response_json = self._call_external_api(prompt)
        content = self._extract_content(response_json)

        return content

    def _build_prompt(self, user_input: str) -> str:
        """
        Вставляет пользовательский ввод в системный шаблон.
        """
        return (
            "You are a professional assistant.\n"
            "Follow security and ethical guidelines strictly.\n"
            "User request:\n"
            f"{user_input}"
        )

    def _call_external_api(self, prompt: str) -> Dict[str, Any]:
        """
        Отправляет запрос к внешнему API по HTTPS.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
        }

        try:
            response = requests.post(
                self._api_url,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise LLMIntegrationError("Ошибка соединения с LLM API") from exc

        if response.status_code != 200:
            raise LLMIntegrationError(
                f"Некорректный статус ответа: {response.status_code}"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise LLMIntegrationError("Ответ LLM не является валидным JSON") from exc

    def _extract_content(self, response_json: Dict[str, Any]) -> str:
        """
        Проверяет структуру ответа модели и извлекает текст.
        """
        try:
            choices = response_json["choices"]
            if not isinstance(choices, list) or not choices:
                raise InvalidLLMResponseError("Отсутствуют варианты ответа")

            message = choices[0]["message"]
            content = message["content"]

            if not isinstance(content, str):
                raise InvalidLLMResponseError("Некорректный формат ответа")

            return sanitize_user_input(content)

        except (KeyError, TypeError) as exc:
            raise InvalidLLMResponseError(
                "Структура ответа LLM не соответствует ожидаемой"
            ) from exc
