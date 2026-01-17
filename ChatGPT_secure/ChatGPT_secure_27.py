from typing import Any, Dict, List
from dataclasses import dataclass

import yaml


# =========================
# EXCEPTIONS
# =========================

class PluginConfigError(Exception):
    pass


class InvalidPluginConfigError(PluginConfigError):
    pass


# =========================
# DATA MODELS
# =========================

@dataclass(frozen=True)
class PluginConfig:
    """
    Строго типизированная конфигурация одного плагина.
    """
    name: str
    enabled: bool
    settings: Dict[str, Any]


# =========================
# CONFIG LOADER
# =========================

class PluginConfigLoader:
    """
    Безопасный загрузчик конфигураций плагинов из YAML.
    """

    def load_from_file(self, path: str) -> List[PluginConfig]:
        """
        Загружает YAML-файл и преобразует его в объекты PluginConfig.
        """
        raw_data = self._load_yaml(path)
        return self._parse_plugins(raw_data)

    def _load_yaml(self, path: str) -> Dict[str, Any]:
        """
        Безопасно читает YAML без выполнения кода.
        """
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            raise PluginConfigError("Ошибка парсинга YAML") from exc
        except OSError as exc:
            raise PluginConfigError("Ошибка чтения файла конфигурации") from exc

        if not isinstance(data, dict):
            raise InvalidPluginConfigError("Корневая структура YAML должна быть словарем")

        return data

    def _parse_plugins(self, data: Dict[str, Any]) -> List[PluginConfig]:
        """
        Проверяет структуру и типы данных конфигурации.
        """
        plugins_raw = data.get("plugins")

        if not isinstance(plugins_raw, list):
            raise InvalidPluginConfigError("Ожидается список плагинов")

        plugins: List[PluginConfig] = []

        for index, plugin in enumerate(plugins_raw):
            if not isinstance(plugin, dict):
                raise InvalidPluginConfigError(
                    f"Плагин #{index} имеет некорректную структуру"
                )

            name = plugin.get("name")
            enabled = plugin.get("enabled")
            settings = plugin.get("settings", {})

            if not isinstance(name, str) or not name:
                raise InvalidPluginConfigError("Имя плагина должно быть строкой")

            if not isinstance(enabled, bool):
                raise InvalidPluginConfigError(
                    f"Поле enabled плагина '{name}' должно быть boolean"
                )

            if not isinstance(settings, dict):
                raise InvalidPluginConfigError(
                    f"Поле settings плагина '{name}' должно быть словарем"
                )

            plugins.append(
                PluginConfig(
                    name=name,
                    enabled=enabled,
                    settings=settings,
                )
            )

        return plugins


# =========================
# PUBLIC API
# =========================

__all__ = [
    "PluginConfigLoader",
    "PluginConfig",
    "PluginConfigError",
    "InvalidPluginConfigError",
]
