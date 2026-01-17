from dataclasses import dataclass
from typing import Dict, List, Protocol, Any

import yaml


# =========================
# Исключения
# =========================

class PluginConfigError(Exception):
    """
    Базовое исключение конфигурации плагинов.
    """


class InvalidPluginConfigError(PluginConfigError):
    """
    Ошибка структуры YAML-файла.
    """


# =========================
# Контракты
# =========================

class PluginApplier(Protocol):
    """
    Контракт для основного приложения,
    к которому применяются плагины.
    """

    def apply_plugin(self, plugin: "PluginConfig") -> None:
        ...


# =========================
# Модели конфигурации
# =========================

@dataclass(frozen=True)
class PluginConfig:
    """
    Конфигурация одного плагина.
    """

    name: str
    enabled: bool
    settings: Dict[str, Any]


@dataclass(frozen=True)
class PluginsConfig:
    """
    Общая конфигурация всех плагинов.
    """

    plugins: List[PluginConfig]


# =========================
# Загрузчик YAML
# =========================

class PluginConfigLoader:
    """
    Загрузчик конфигурации плагинов из YAML.
    """

    def __init__(self, config_path: str) -> None:
        self._config_path = config_path

    # =========================
    # Public API
    # =========================

    def load(self) -> PluginsConfig:
        """
        Загружает и парсит YAML-файл.
        """
        raw_config = self._read_yaml()
        return self._parse_plugins(raw_config)

    def apply_to(self, app: PluginApplier) -> None:
        """
        Применяет конфигурацию плагинов к приложению.
        """
        plugins_config = self.load()

        for plugin in plugins_config.plugins:
            if plugin.enabled:
                app.apply_plugin(plugin)

    # =========================
    # Внутренняя логика
    # =========================

    def _read_yaml(self) -> Dict[str, Any]:
        """
        Читает YAML-файл конфигурации.
        """
        try:
            with open(self._config_path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
        except OSError as exc:
            raise PluginConfigError(
                f"Unable to read config file: {self._config_path}"
            ) from exc

        if not isinstance(data, dict):
            raise InvalidPluginConfigError("Root YAML node must be a mapping")

        return data

    def _parse_plugins(self, data: Dict[str, Any]) -> PluginsConfig:
        """
        Преобразует YAML-данные в объекты.
        """
        plugins_raw = data.get("plugins")

        if not isinstance(plugins_raw, list):
            raise InvalidPluginConfigError(
                "'plugins' must be a list"
            )

        plugins: List[PluginConfig] = []

        for item in plugins_raw:
            plugins.append(self._parse_single_plugin(item))

        return PluginsConfig(plugins=plugins)

    def _parse_single_plugin(self, data: Dict[str, Any]) -> PluginConfig:
        """
        Парсит один плагин.
        """
        if not isinstance(data, dict):
            raise InvalidPluginConfigError("Plugin entry must be a mapping")

        try:
            name = str(data["name"])
            enabled = bool(data.get("enabled", True))
            settings = dict(data.get("settings", {}))
        except KeyError as exc:
            raise InvalidPluginConfigError(
                "Plugin config must contain 'name'"
            ) from exc

        return PluginConfig(
            name=name,
            enabled=enabled,
            settings=settings,
        )


# =========================
# Пример интеграции
# =========================

class Application:
    """
    Пример основного приложения.
    """

    def apply_plugin(self, plugin: PluginConfig) -> None:
        print(f"Applying plugin: {plugin.name}")
        print(f"Settings: {plugin.settings}")


if __name__ == "__main__":
    loader = PluginConfigLoader("plugins.yaml")
    app = Application()
    loader.apply_to(app)
