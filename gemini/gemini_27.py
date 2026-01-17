import yaml
import importlib
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PluginLoader")

@dataclass
class PluginMetadata:
    """Объектное представление настроек плагина."""
    name: str
    module_path: str
    enabled: bool
    settings: Dict[str, Any]

class PluginConfigLoader:
    """
    Загрузчик плагинов, отвечающий за чтение YAML и инициализацию компонентов.
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.plugins: List[Any] = []

    def _load_yaml(self) -> Dict[str, Any]:
        """Чтение и базовый парсинг YAML-файла."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.error(f"Файл конфигурации {self.config_path} не найден.")
            return {}
        except yaml.YAMLError as e:
            logger.error(f"Ошибка парсинга YAML: {e}")
            return {}

    def _instantiate_plugin(self, metadata: PluginMetadata) -> Optional[Any]:
        """Динамический импорт модуля и создание экземпляра класса плагина."""
        try:
            # Импорт модуля (например, 'plugins.auth_provider')
            module = importlib.import_module(metadata.module_path)
            
            # Предполагаем, что в модуле есть класс 'Plugin' (стандарт интерфейса)
            plugin_class = getattr(module, 'Plugin')
            
            # Инициализация объекта с передачей настроек
            return plugin_class(settings=metadata.settings)
        except (ImportError, AttributeError) as e:
            logger.error(f"Не удалось загрузить плагин {metadata.name}: {e}")
            return None

    def bootstrap(self) -> List[Any]:
        """
        Запускает процесс инициализации всех включенных плагинов.
        """
        config_data = self._load_yaml()
        plugin_configs = config_data.get('plugins', [])

        for p_conf in plugin_configs:
            metadata = PluginMetadata(
                name=p_conf.get('name', 'Unknown'),
                module_path=p_conf.get('module'),
                enabled=p_conf.get('enabled', False),
                settings=p_conf.get('settings', {})
            )

            if metadata.enabled:
                logger.info(f"Инициализация плагина: {metadata.name}...")
                instance = self._instantiate_plugin(metadata)
                if instance:
                    self.plugins.append(instance)
            else:
                logger.info(f"Плагин {metadata.name} отключен в конфиге.")

        return self.plugins

# --- Пример структуры YAML (config.yaml) ---
# plugins:
#   - name: "EmailNotifier"
#     module: "app.plugins.email"
#     enabled: true
#     settings:
#       smtp_server: "localhost"
#       port: 1025
#
#   - name: "SlackLogger"
#     module: "app.plugins.slack"
#     enabled: false

if __name__ == "__main__":
    # Имитация запуска системы
    loader = PluginConfigLoader("plugins_config.yaml")
    # loaded_plugins = loader.bootstrap()
    print("Система PluginConfigLoader готова к работе.")